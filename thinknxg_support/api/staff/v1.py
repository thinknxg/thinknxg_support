"""thinkNXG Support staff API, version 1 (Agent Apps). Contract: docs/agent-api.md.

Every endpoint: staff_auth.require_staff() first, then access to the record (queue visibility for conversations,
Helpdesk permissions for tickets). Writes reuse the server functions the web console uses.
"""
from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import cint, get_datetime, now_datetime, strip_html

from thinknxg_support.api.staff import cursors
from thinknxg_support.api.staff.errors import ChannelActionRequired, Conflict
from thinknxg_support.integrations import staff_auth

CONV = "Support Conversation Link"
MSG = "Support Portal Message"
READ = "Support Agent Read State"
API_VERSION = 1


def _iso(v):
    return get_datetime(v).isoformat() if v else None


# ------------------------------------------------------------------ sign-in and bootstrap
@frappe.whitelist(allow_guest=True, methods=["GET"])
def auth_config():
    """Public sign-in details for the apps (no secrets): the site's OAuth endpoints and client id."""
    if not frappe.db.exists("DocType", staff_auth.SETTINGS) or not staff_auth.settings().enabled:
        return {"enabled": False}
    s = staff_auth.settings()
    client_id = frappe.db.get_value("OAuth Client", s.oauth_client, "client_id") if s.oauth_client else None
    return {"enabled": bool(client_id), "api_version": API_VERSION, "site_name": frappe.local.site,
            "client_id": client_id, "scopes": "all openid",
            # the OAuth Client's own list is what sign-in is checked against; the settings are the fallback
            "redirect_uris": staff_auth.client_redirect_uris(s.oauth_client) or staff_auth.redirect_uris(),
            **staff_auth.oauth_endpoints()}


def _member_queues(user: str) -> list[str]:
    return frappe.get_all("Support Chat Queue Member", filters={"user": user, "active": 1, "parenttype": "Support Chat Queue"},
                          pluck="parent", distinct=True)


@frappe.whitelist(methods=["GET"])
def bootstrap():
    staff_auth.require_staff()
    from thinknxg_support.integrations import capabilities, helpdesk_agent
    from thinknxg_support.utils import settings as portal_settings

    user = frappe.session.user
    u = frappe.db.get_value("User", user, ["full_name", "email", "user_image"], as_dict=True) or {}
    caps = capabilities.get() if hasattr(capabilities, "get") else {}
    ps = portal_settings()
    s = staff_auth.settings()
    mine = set(_member_queues(user))
    queues = frappe.get_all("Support Chat Queue", or_filters={"enabled": 1, "name": ["in", list(mine) or [""]]},
                            pluck="name", order_by="priority desc")
    return {
        "api_version": API_VERSION, "server_time": now_datetime().isoformat(),
        "site": {"url": frappe.utils.get_url(), "name": frappe.local.site,
                 "app_version": frappe.get_attr("thinknxg_support.__version__")},
        "agent": {"user": user, "full_name": u.get("full_name") or user, "email": u.get("email") or user,
                  "image": u.get("user_image"), "is_manager": staff_auth.is_manager(),
                  "helpdesk_agent": helpdesk_agent.is_hd_agent() if helpdesk_agent.available() else False},
        "capabilities": {
            "conversations": True, "live_chat": bool(ps.get("enable_live_chat")),
            "whatsapp": bool(ps.get("enable_whatsapp")), "raven": bool(ps.get("enable_raven")),
            "helpdesk": helpdesk_agent.available(), "assistant": _assistant_on(),
            "wrap_up": True, "canned_responses": True, "alerts": True, "push": bool(s.push_enabled),
            "realtime": False,  # first release: authenticated polling (see docs/agent-api.md)
            "integrations": {k: bool((v or {}).get("installed")) for k, v in (caps.get("apps") or {}).items()}
            if isinstance(caps, dict) else {},
        },
        "queues": [{"name": q, "member": q in mine} for q in queues],
        "poll": {"inbox_seconds": s.inbox_poll_seconds or 10, "thread_seconds": s.thread_poll_seconds or 4,
                 "alerts_seconds": s.alerts_poll_seconds or 15},
    }


def _assistant_on() -> bool:
    try:
        return bool(frappe.get_cached_doc("Support AI Settings").enable_ai)
    except Exception:
        return False


# ------------------------------------------------------------------ conversation access (lists and lookups alike)
def _scope_sql(user: str) -> tuple[str, list]:
    """Agents see conversations in their queues, assigned to them, or not in any queue. Managers see all."""
    if staff_auth.is_manager(user):
        return "1=1", []
    queues = _member_queues(user)
    parts, args = ["c.assigned_agent = %s", "coalesce(c.queue, '') = ''"], [user]
    if queues:
        parts.append("c.queue in %s")
        args.append(tuple(queues))
    return "(" + " or ".join(parts) + ")", args


def _can_access(conv, user: str | None = None) -> bool:
    user = user or frappe.session.user
    if staff_auth.is_manager(user):
        return True
    return bool(conv.get("assigned_agent") == user or not conv.get("queue") or conv.get("queue") in _member_queues(user))


def _conv(name: str, ptype: str = "read"):
    staff_auth.require_staff()
    if not frappe.db.exists(CONV, name):
        raise frappe.DoesNotExistError(_("Conversation not found."))
    doc = frappe.get_doc(CONV, name)
    doc.check_permission(ptype)
    if not _can_access(doc):
        raise frappe.PermissionError(_("This conversation is in a queue you are not part of."))
    return doc


def _display_name(r) -> str:
    from thinknxg_support.api.v1.agent import _display_name as dn

    return dn(r)


def _agent(user):
    return {"user": user, "name": frappe.utils.get_fullname(user)} if user else None


def _read_marker(user: str, names: list[str]) -> dict:
    if not names:
        return {}
    return {r.conversation: r.last_read_at for r in frappe.get_all(READ, filters={"user": user, "conversation": ["in", names]},
                                                                   fields=["conversation", "last_read_at"])}


def _unread_counts(user: str, names: list[str]) -> dict:
    markers = _read_marker(user, names)
    out = {}
    for n in names:
        cond = {"conversation": n, "direction": "Inbound"}
        if markers.get(n):
            cond["creation"] = [">", markers[n]]
        out[n] = frappe.db.count(MSG, cond)
    return out


CONV_FIELDS = ("c.name, c.subject, c.status, c.channel, c.customer, c.is_guest, c.guest_name, c.whatsapp_number, "
               "c.whatsapp_profile_name, c.started_by, c.assigned_agent, c.last_activity_at, c.last_message_reference, "
               "c.whatsapp_window_expires, c.helpdesk_ticket, c.handling, c.queue, c.modified")


def _summary(r, unread: int, preview: str = "") -> dict:
    return {
        "id": r.name, "subject": r.subject or "", "display_name": _display_name(r), "channel": r.channel or "Portal",
        "status": r.status, "handling": r.handling, "queue": r.queue, "assignee": _agent(r.assigned_agent),
        "customer": r.customer, "is_guest": bool(cint(r.is_guest)), "ticket": r.helpdesk_ticket,
        "last_activity_at": _iso(r.last_activity_at or r.modified), "unread": unread, "preview": preview,
        "whatsapp_window_open": bool(r.whatsapp_window_expires and get_datetime(r.whatsapp_window_expires) > now_datetime())
        if r.channel == "WhatsApp" else None,
        "version": str(r.modified),
    }


@frappe.whitelist(methods=["GET"])
def conversations(view: str = "all", channel: str | None = None, status: str = "open", queue: str | None = None,
                  q: str | None = None, cursor: str | None = None, limit: int = 30):
    """Paginated inbox, newest activity first. view: all | mine | unassigned | waiting (handed to people, nobody yet)."""
    staff_auth.require_staff()
    if not frappe.has_permission(CONV, "read"):
        raise frappe.PermissionError
    user = frappe.session.user
    limit = max(1, min(cint(limit) or 30, 50))
    scope, args = _scope_sql(user)
    where = [scope]
    if view == "mine":
        where.append("c.assigned_agent = %s"); args.append(user)
    elif view == "unassigned":
        where.append("coalesce(c.assigned_agent, '') = ''")
    elif view == "waiting":
        where.append("c.handling = 'Queued' and coalesce(c.assigned_agent, '') = ''")
    if channel in ("Portal", "Live Chat", "WhatsApp"):
        where.append("c.channel = %s"); args.append(channel)
    if status == "open":
        where.append("c.status != 'Closed'")
    elif status == "closed":
        where.append("c.status = 'Closed'")
    if queue:
        where.append("c.queue = %s"); args.append(queue)
    if q:
        like = f"%{strip_html(q)[:60]}%"
        where.append("(c.subject like %s or c.guest_name like %s or c.guest_email like %s or c.whatsapp_number like %s "
                     "or c.whatsapp_profile_name like %s or c.customer like %s or c.name like %s)")
        args += [like] * 7
    after = cursors.decode(cursor)
    if after:
        where.append("(coalesce(c.last_activity_at, c.modified), c.name) < (%s, %s)")
        args += [after["t"], after["n"]]
    rows = frappe.db.sql(f"""select {CONV_FIELDS}, coalesce(c.last_activity_at, c.modified) as sort_at
        from `tab{CONV}` c where {' and '.join(where)}
        order by sort_at desc, c.name desc limit %s""", (*args, limit + 1), as_dict=True)
    page = rows[:limit]
    refs = [r.last_message_reference for r in page if r.last_message_reference]
    previews = {}
    if refs:
        for m in frappe.get_all(MSG, filters={"name": ["in", refs], "is_internal": 0},
                                fields=["name", "content", "direction", "sender_type"]):
            prefix = "" if m.direction == "Inbound" else ((m.sender_type or "") + ": ")
            previews[m.name] = (prefix + strip_html(m.content or ""))[:120]
    unread = _unread_counts(user, [r.name for r in page])
    nxt = cursors.encode(str(page[-1].sort_at), page[-1].name) if len(rows) > limit and page else None
    return {"items": [_summary(r, unread.get(r.name, 0), previews.get(r.last_message_reference, "")) for r in page],
            "next_cursor": nxt}


def _actions(doc) -> dict:
    user = frappe.session.user
    from thinknxg_support.integrations import whatsapp

    window = whatsapp.window_open(doc) if doc.channel == "WhatsApp" else None
    open_ = doc.status != "Closed"
    try:
        from thinknxg_support.integrations.ai.engine import automation_applies

        can_return = bool(open_ and doc.handling != "Bot" and automation_applies(doc))
    except Exception:
        can_return = False
    from thinknxg_support.integrations import helpdesk_agent

    return {"claim": open_ and doc.assigned_agent != user, "transfer": open_, "reply": open_ and window is not False,
            "link_customer": True, "create_ticket": bool(not doc.helpdesk_ticket and helpdesk_agent.available()),
            "note": True, "close": open_, "take_over": open_ and doc.handling == "Bot", "return_to_assistant": can_return,
            "whatsapp_window_open": window}


def conversation_detail(doc) -> dict:
    r = frappe._dict(doc.as_dict())
    unread = _unread_counts(frappe.session.user, [doc.name]).get(doc.name, 0)
    out = _summary(r, unread)
    out.update({
        "contact": {"name": doc.get("guest_name") if doc.is_guest else frappe.db.get_value("User", doc.started_by, "full_name"),
                    "email": doc.get("guest_email") or (frappe.db.get_value("User", doc.started_by, "email") if doc.started_by else None),
                    "phone": doc.get("guest_phone") or (f"+{doc.whatsapp_number}" if doc.whatsapp_number else None)},
        "customer_name": frappe.db.get_value("Customer", doc.customer, "customer_name") if doc.customer else None,
        "created_at": _iso(doc.creation), "handoff_reason": doc.get("handoff_reason"),
        "actions": _actions(doc),
        "read_up_to": _iso(_read_marker(frappe.session.user, [doc.name]).get(doc.name)),
    })
    return out


@frappe.whitelist(methods=["GET"])
def conversation(name: str):
    return conversation_detail(_conv(name))


def _message(m) -> dict:
    try:
        actions = json.loads(m.get("actions_json") or "{}")
    except ValueError:
        actions = {}
    return {"id": m.name, "direction": "inbound" if m.direction == "Inbound" else ("internal" if cint(m.is_internal) else "outbound"),
            "internal": bool(cint(m.is_internal)), "sender_type": m.sender_type, "author": m.sender_name or m.sender,
            "author_user": m.sender, "html": m.content or "", "created_at": _iso(m.creation),
            "attachment": {"name": (m.attachment or "").rsplit("/", 1)[-1]} if m.attachment else None,
            "delivery": {"status": m.delivery_status, "error": m.delivery_error} if m.delivery_status else None,
            "client_request_id": m.client_message_id, "read_by_customer": bool(cint(m.read_by_customer)),
            "actions": actions}


MSG_FIELDS = ["name", "direction", "sender", "sender_name", "content", "attachment", "is_internal", "creation",
              "delivery_status", "delivery_error", "sender_type", "client_message_id", "read_by_customer", "actions_json"]


@frappe.whitelist(methods=["GET"])
def messages(name: str, before: str | None = None, after: str | None = None, limit: int = 30):
    """Timeline page, oldest first within the page. `before` pages back; `after` returns newer messages (polling)."""
    _conv(name)
    limit = max(1, min(cint(limit) or 30, 100))
    b, a = cursors.decode(before), cursors.decode(after)
    cond, args = ["conversation = %s"], [name]
    if b:
        cond.append("(creation, name) < (%s, %s)"); args += [b["t"], b["n"]]
    if a:
        cond.append("(creation, name) > (%s, %s)"); args += [a["t"], a["n"]]
    order = "asc" if a else "desc"
    rows = frappe.db.sql(f"select {', '.join(MSG_FIELDS)} from `tab{MSG}` where {' and '.join(cond)} "
                         f"order by creation {order}, name {order} limit %s", (*args, limit + 1), as_dict=True)
    more = len(rows) > limit
    rows = rows[:limit]
    if not a:
        rows = list(reversed(rows))  # oldest first within the page
    first, last = (rows[0], rows[-1]) if rows else (None, None)
    older = bool(more and not a)  # pages back exist only when paging backwards ran out of room
    return {"items": [_message(m) for m in rows],
            "before_cursor": cursors.encode(str(first.creation), first.name) if first and older else None,
            "has_more_before": older,
            # when paging back, the newest row of the conversation is not on this page: keep the caller's cursor
            "latest_cursor": (cursors.encode(str(last.creation), last.name) if last and not b else after)}


@frappe.whitelist(methods=["POST"])
def mark_read(name: str, message: str):
    """Explicit read acknowledgement for this agent, up to and including `message`. Only moves forward."""
    doc = _conv(name)
    m = frappe.db.get_value(MSG, message, ["conversation", "creation"], as_dict=True)
    if not m or m.conversation != doc.name:
        frappe.throw(_("Message not in this conversation."))
    user = frappe.session.user
    row = frappe.db.get_value(READ, {"user": user, "conversation": doc.name}, ["name", "last_read_at"], as_dict=True)
    if row and row.last_read_at and get_datetime(row.last_read_at) >= get_datetime(m.creation):
        return {"read_up_to": _iso(row.last_read_at)}
    if row:
        frappe.db.set_value(READ, row.name, {"last_read_message": message, "last_read_at": m.creation}, update_modified=False)
    else:
        frappe.get_doc({"doctype": READ, "user": user, "conversation": doc.name, "last_read_message": message,
                        "last_read_at": m.creation}).insert(ignore_permissions=True)
    # keep the web console's shared flag in step for messages this agent has now read
    frappe.db.sql(f"update `tab{MSG}` set read_by_agent=1 where conversation=%s and direction='Inbound' and creation<=%s",
                  (doc.name, m.creation))
    if not frappe.db.exists(MSG, {"conversation": doc.name, "direction": "Inbound", "read_by_agent": 0}):
        frappe.db.set_value(CONV, doc.name, "unread_agent", 0, update_modified=False)
    return {"read_up_to": _iso(m.creation)}


# ------------------------------------------------------------------ claim, transfer, takeover, close
def _lock(name: str):
    """Row lock for the rest of this request: two agents claiming at once are serialised; one wins."""
    return frappe.db.sql(f"select name, assigned_agent, status, handling, queue, modified from `tab{CONV}` where name=%s for update",
                         name, as_dict=True)[0]


@frappe.whitelist(methods=["POST"])
def claim(name: str):
    doc = _conv(name, "write")
    row = _lock(name)
    user = frappe.session.user
    if row.status == "Closed":
        raise Conflict(_("This conversation is closed."), current=conversation_detail(doc))
    if row.assigned_agent and row.assigned_agent != user:
        raise Conflict(_("{0} already has this conversation.").format(frappe.utils.get_fullname(row.assigned_agent)),
                       current=conversation_detail(doc))
    if row.assigned_agent != user:
        from thinknxg_support.integrations import conversations, routing

        doc.reload()
        routing.assign(doc, user, doc.queue, "Manual")
        if doc.handling in ("Bot", "Queued", None, ""):
            doc.db_set("handling", "Agent", update_modified=False)
        conversations.publish_agent_event(doc, "assigned")
    return conversation_detail(frappe.get_doc(CONV, name))


@frappe.whitelist(methods=["POST"])
def transfer(name: str, user: str | None = None, queue: str | None = None, expected_assignee: str | None = None):
    doc = _conv(name, "write")
    row = _lock(name)
    if expected_assignee is not None and (row.assigned_agent or "") != (expected_assignee or ""):
        raise Conflict(_("The owner changed before your transfer. Reload to see the latest."), current=conversation_detail(doc))
    if user and not staff_auth.is_staff(user):
        frappe.throw(_("{0} is not a support agent.").format(user))
    from thinknxg_support.api.v1 import agent as console

    console.transfer(name, user=user, queue=queue)
    return conversation_detail(frappe.get_doc(CONV, name))


@frappe.whitelist(methods=["POST"])
def take_over(name: str):
    _conv(name, "write")
    _lock(name)
    from thinknxg_support.api.v1 import agent as console

    console.take_over(name)
    return conversation_detail(frappe.get_doc(CONV, name))


@frappe.whitelist(methods=["POST"])
def return_to_assistant(name: str):
    _conv(name, "write")
    from thinknxg_support.api.v1 import agent as console

    console.return_to_assistant(name)
    return conversation_detail(frappe.get_doc(CONV, name))


@frappe.whitelist(methods=["GET"])
def closing_form():
    staff_auth.require_staff()
    from thinknxg_support.integrations import agent_tools

    return agent_tools.closing_form()


@frappe.whitelist(methods=["POST"])
def close(name: str, reason: str | None = None, notes: str | None = None, answers=None, send_closing_message: int = 1,
          expected_status: str | None = None):
    doc = _conv(name, "write")
    row = _lock(name)
    if expected_status and row.status != expected_status:
        raise Conflict(_("This conversation changed (now {0}).").format(row.status), current=conversation_detail(doc))
    from thinknxg_support.integrations import agent_tools

    agent_tools.end_chat(name, reason=reason, notes=notes, answers=answers, send_closing_message=send_closing_message)
    return conversation_detail(frappe.get_doc(CONV, name))


@frappe.whitelist(methods=["GET"])
def canned_responses(channel: str | None = None):
    staff_auth.require_staff()
    from thinknxg_support.integrations import agent_tools

    return agent_tools.canned_responses(channel)


# ------------------------------------------------------------------ replies and notes (idempotent)
def _text_html(text: str) -> str:
    from thinknxg_support.integrations.conversations import _text_to_html

    return _text_to_html((text or "").strip())


@frappe.whitelist(methods=["POST"])
def reply(name: str, text: str, client_request_id: str, internal: int = 0):
    """Reply to the customer (internal=0) or add a staff-only note (internal=1). Retrying with the same
    client_request_id returns the first message instead of sending again."""
    doc = _conv(name, "write")
    cid = (client_request_id or "").strip()[:64]
    if len(cid) < 8:
        frappe.throw(_("client_request_id is required (use a UUID)."))
    if not (text or "").strip() and not getattr(getattr(frappe, "request", None), "files", None):
        frappe.throw(_("Write a message first."))
    existing = frappe.db.get_value(MSG, {"conversation": doc.name, "client_message_id": cid}, MSG_FIELDS, as_dict=True)
    if existing:
        return {"message": _message(existing), "duplicate": True}
    internal = cint(internal)
    from thinknxg_support.utils import uploaded_files

    files = uploaded_files()[:1]
    if files and doc.channel == "WhatsApp" and not internal:
        raise ChannelActionRequired(_("Files cannot be sent over WhatsApp from the app yet. Share a link instead, or "
                                      "attach the file to an internal note."), "attachments_unsupported", [])
    if not internal and doc.status == "Closed":
        raise ChannelActionRequired(_("This conversation is closed."), "conversation_closed", [])
    if not internal and doc.channel == "WhatsApp":
        from thinknxg_support.integrations import whatsapp

        if not whatsapp.window_open(doc):
            raise ChannelActionRequired(
                _("WhatsApp only allows free replies within 24 hours of the customer's last message. "
                  "Send an approved template from the web console, or wait for the customer to write."),
                "whatsapp_window_closed", [{"action": "open_web_console", "label": _("Open in the web console")}])
    from thinknxg_support.integrations import conversations

    out = conversations.post_agent_message(doc, _text_html(text) if (text or "").strip() else "", internal=internal,
                                           source="app", client_message_id=cid, files=files)
    msg = frappe.db.get_value(MSG, out.get("name") or {"conversation": doc.name, "client_message_id": cid}, MSG_FIELDS,
                              as_dict=True)
    return {"message": _message(msg), "duplicate": bool(out.get("duplicate"))}


# ------------------------------------------------------------------ tickets (Helpdesk)
def _hd():
    staff_auth.require_staff()
    from thinknxg_support.integrations import helpdesk_agent

    if not helpdesk_agent.available():
        raise ChannelActionRequired(_("Helpdesk is not installed on this site."), "helpdesk_unavailable")
    return helpdesk_agent


@frappe.whitelist(methods=["GET"])
def tickets(view: str = "mine", status: str | None = "open", priority: str | None = None, q: str | None = None,
            cursor: str | None = None, limit: int = 30):
    return _hd().list_tickets(view=view, status=status, priority=priority, q=q, cursor=cursor, limit=limit)


@frappe.whitelist(methods=["GET"])
def ticket(name: str):
    return _hd().ticket_detail(name)


@frappe.whitelist(methods=["GET"])
def ticket_timeline(name: str, cursor: str | None = None, limit: int = 30):
    return _hd().timeline(name, cursor=cursor, limit=limit)


def _once(request_id: str, action: str, reference: str, fn):
    """Run `fn` once per client request id; a retry gets the stored result."""
    rid = (request_id or "").strip()[:64]
    if len(rid) < 8:
        frappe.throw(_("client_request_id is required (use a UUID)."))
    key = f"{frappe.session.user}:{rid}"
    row = frappe.db.get_value("Support Agent Request", {"request_id": key}, ["result", "action", "reference"], as_dict=True)
    if row:
        if row.action != action or row.reference != reference:
            frappe.throw(_("This client_request_id was already used for something else."))
        return {**json.loads(row.result or "{}"), "duplicate": True}
    log = frappe.get_doc({"doctype": "Support Agent Request", "request_id": key, "user": frappe.session.user,
                          "action": action, "reference": reference})
    try:
        log.insert(ignore_permissions=True)  # unique request_id: a concurrent retry fails here
    except frappe.DuplicateEntryError:
        frappe.db.rollback()
        row = frappe.db.get_value("Support Agent Request", {"request_id": key}, "result")
        return {**json.loads(row or "{}"), "duplicate": True}
    try:
        result = fn()
    except Exception:
        frappe.db.delete("Support Agent Request", {"name": log.name})  # nothing happened: a retry may run again
        raise
    frappe.db.set_value("Support Agent Request", log.name, "result", json.dumps(result, default=str), update_modified=False)
    return {**result, "duplicate": False}


@frappe.whitelist(methods=["POST"])
def ticket_reply(name: str, text: str, client_request_id: str):
    hd = _hd()
    from thinknxg_support.utils import uploaded_files

    files = uploaded_files()
    if not (text or "").strip():
        frappe.throw(_("Write a message first."))
    return _once(client_request_id, "ticket_reply", name, lambda: hd.reply(name, _text_html(text), files=files))


@frappe.whitelist(methods=["POST"])
def ticket_note(name: str, text: str, client_request_id: str):
    hd = _hd()
    if not (text or "").strip():
        frappe.throw(_("Write a note first."))
    return _once(client_request_id, "ticket_note", name, lambda: hd.note(name, _text_html(text)))


@frappe.whitelist(methods=["POST"])
def ticket_update(name: str, status: str | None = None, priority: str | None = None, team: str | None = None,
                  expected_modified: str | None = None):
    return _hd().update(name, {"status": status, "priority": priority, "agent_group": team}, expected_modified)


@frappe.whitelist(methods=["POST"])
def ticket_assign(name: str, agent: str | None = None, expected_assignees=None):
    exp = frappe.parse_json(expected_assignees) if isinstance(expected_assignees, str) else expected_assignees
    return _hd().assign(name, agent or frappe.session.user, exp)


# ------------------------------------------------------------------ alerts, notification links, devices
@frappe.whitelist(methods=["GET"])
def alerts(since: float | None = None):
    """Open (stored) alerts, plus unstored ones (new messages …) since the cursor from the previous poll."""
    staff_auth.require_staff()
    from thinknxg_support.integrations import alerts as al

    since = float(since) if since not in (None, "", "null") else None
    events, cursor = al.recent_events(frappe.session.user, since) if al.is_agent(frappe.session.user) else ([], since or 0)
    return {"items": al.my_alerts(), "events": [{k: e.get(k) for k in ("id", "kind", "title", "body", "reference_doctype",
                                                                      "reference_name", "priority")} for e in events],
            "cursor": cursor}


@frappe.whitelist(methods=["POST"])
def acknowledge_alerts(ids):
    staff_auth.require_staff()
    from thinknxg_support.integrations import alerts as al

    return {"acknowledged": al.acknowledge(ids)}


@frappe.whitelist(methods=["GET"])
def open_target(doctype: str, name: str):
    """Where a notification or alert link should go, checked again for this agent. 403/404 when not allowed."""
    staff_auth.require_staff()
    if doctype == CONV:
        _conv(name)
        return {"kind": "conversation", "id": name}
    if doctype == "HD Ticket":
        _hd().get_ticket(name)
        return {"kind": "ticket", "id": name}
    if doctype == "Support Escalation":
        e = frappe.get_doc(doctype, name)
        e.check_permission("read")
        if e.reference_doctype in (CONV, "HD Ticket"):
            return open_target(e.reference_doctype, e.reference_name)
        return {"kind": "web", "url": frappe.utils.get_url(f"/app/support-escalation/{name}")}
    raise frappe.PermissionError(_("This link cannot be opened in the app."))


@frappe.whitelist(methods=["POST"])
def register_device(push_token: str, platform: str, device_name: str | None = None, app_version: str | None = None):
    staff_auth.require_staff()
    import hashlib

    if platform not in ("Android", "iOS", "Windows"):
        frappe.throw(_("Unknown platform."))
    token = (push_token or "").strip()
    if not token or len(token) > 4096:
        frappe.throw(_("Invalid push token."))
    h = hashlib.sha256(token.encode()).hexdigest()
    existing = frappe.db.get_value("Support Agent Device", {"token_hash": h}, "name")
    values = {"user": frappe.session.user, "platform": platform, "device_name": (device_name or "")[:140],
              "app_version": (app_version or "")[:40], "enabled": 1, "push_token": token, "token_hash": h,
              "last_seen": now_datetime()}
    if existing:  # a token moves to whoever signs in on that device now
        frappe.db.set_value("Support Agent Device", existing, values)
        return {"device": existing}
    d = frappe.get_doc({"doctype": "Support Agent Device", **values}).insert(ignore_permissions=True)
    return {"device": d.name}


@frappe.whitelist(methods=["POST"])
def sign_out(push_token: str | None = None):
    """Called by the app before it revokes its token and clears local data: stop push to this device."""
    staff_auth.require_staff()
    import hashlib

    if push_token:
        h = hashlib.sha256(push_token.strip().encode()).hexdigest()
        frappe.db.delete("Support Agent Device", {"token_hash": h, "user": frappe.session.user})
    return {"ok": True}


# ------------------------------------------------------------------ workspace: canned, files, transfer, history, live
@frappe.whitelist(methods=["POST"])
def canned_render(name: str, conversation: str):
    """A canned response with its placeholders filled for this conversation. Counts as used."""
    doc = _conv(conversation)
    from thinknxg_support.integrations import agent_tools

    if name.startswith("hd:"):
        hd = frappe.get_doc("HD Canned Response", name[3:])
        hd.check_permission("read")
        html = hd.message or ""
    else:
        c = frappe.get_doc("Support Canned Response", name)
        c.check_permission("read")
        if not cint(c.enabled):
            frappe.throw(_("This canned response is switched off."))
        html = c.content or ""
    customer = _display_name(frappe._dict(doc.as_dict())) or ""
    agent = frappe.utils.get_fullname(frappe.session.user) or ""
    company = frappe.db.get_value("Customer", doc.customer, "customer_name") if doc.customer else ""
    values = {"customer_name": customer, "customer_first_name": customer.split(" ")[0] if customer else "",
              "agent_name": agent, "agent_first_name": agent.split(" ")[0] if agent else "", "company": company or ""}
    for k, v in values.items():
        html = html.replace("{" + k + "}", frappe.utils.escape_html(v))
    agent_tools.canned_used(name)
    return {"html": html, "text": plain_text(html)}


def plain_text(html: str) -> str:
    import re
    from html import unescape

    t = re.sub(r"(?i)<br\s*/?>", "\n", html or "")
    t = re.sub(r"(?i)</(p|div|li|h[1-6])>", "\n", t)
    t = unescape(re.sub(r"<[^>]+>", "", t))
    return re.sub(r"\n{3,}", "\n\n", t).strip()


@frappe.whitelist(methods=["GET"])
def attachment(message: str):
    """Download one message's file after checking access to its conversation. Files never travel inside lists."""
    staff_auth.require_staff()
    row = frappe.db.get_value(MSG, message, ["conversation", "attachment"], as_dict=True)
    if not row or not row.attachment:
        raise frappe.DoesNotExistError(_("Attachment not found."))
    _conv(row.conversation)
    file_name = frappe.db.get_value("File", {"file_url": row.attachment, "attached_to_doctype": MSG,
                                             "attached_to_name": message}) or \
        frappe.db.get_value("File", {"file_url": row.attachment, "attached_to_doctype": CONV,
                                     "attached_to_name": row.conversation})
    if not file_name:
        raise frappe.DoesNotExistError(_("Attachment not found."))
    from thinknxg_support.audit import log_event
    from thinknxg_support.utils import stream_file

    log_event("Download", reference_doctype=CONV, reference_name=row.conversation, details={"message": message}, commit=True)
    stream_file(file_name)


@frappe.whitelist(methods=["GET"])
def ticket_attachment(name: str, file: str):
    hd = _hd()
    hd.get_ticket(name)
    if not hd.file_on_ticket(name, file):
        raise frappe.DoesNotExistError(_("Attachment not found."))
    from thinknxg_support.utils import stream_file

    stream_file(file)


@frappe.whitelist(methods=["GET"])
def transfer_targets(name: str):
    """Who and where this conversation can go: agents (online first, with their open chats) and queues."""
    doc = _conv(name)
    from thinknxg_support.integrations import alerts as al, realtime

    in_queue = set(al.queue_members(doc.queue)) if doc.queue else set()
    users = (in_queue | set(al.all_agents())) - {frappe.session.user}
    load = {}
    if users:
        load = {r.assigned_agent: r.n for r in frappe.db.sql(
            f"select assigned_agent, count(*) n from `tab{CONV}` where status != 'Closed' and assigned_agent in %s "
            "group by assigned_agent", (tuple(users),), as_dict=True)}
    agents = [{"user": u, "name": frappe.utils.get_fullname(u), "online": bool(realtime.is_online(u)),
               "open_chats": int(load.get(u, 0)), "in_queue": u in in_queue} for u in users]
    agents.sort(key=lambda a: (not a["online"], not a["in_queue"], a["open_chats"], (a["name"] or "").lower()))
    queues = frappe.get_all("Support Chat Queue", filters={"enabled": 1}, pluck="name", order_by="priority desc")
    return {"agents": agents[:200], "queues": queues, "current": {"user": doc.assigned_agent, "queue": doc.queue}}


@frappe.whitelist(methods=["GET"])
def customer_history(name: str):
    """Earlier conversations and tickets of the same customer (same account, e-mail or WhatsApp number), limited to
    what this agent may open."""
    doc = _conv(name)
    conds, args = [], []
    for field, value in (("customer", doc.customer), ("started_by", doc.started_by), ("guest_email", doc.get("guest_email")),
                         ("whatsapp_number", doc.get("whatsapp_number"))):
        if value and value != "Guest":
            conds.append(f"c.{field} = %s")
            args.append(value)
    convs = []
    if conds:
        scope, sargs = _scope_sql(frappe.session.user)
        rows = frappe.db.sql(f"""select {CONV_FIELDS}, coalesce(c.last_activity_at, c.modified) as sort_at
            from `tab{CONV}` c where ({' or '.join(conds)}) and c.name != %s and {scope}
            order by sort_at desc limit 20""", (*args, doc.name, *sargs), as_dict=True)
        convs = [_summary(r, 0) for r in rows]
    tickets_out = []
    from thinknxg_support.integrations import helpdesk_agent

    email = doc.get("guest_email") or (frappe.db.get_value("User", doc.started_by, "email") if doc.started_by else None)
    if helpdesk_agent.available() and (email or doc.customer):
        T = "HD Ticket"
        or_filters = [[T, "raised_by", "=", email]] if email else []
        if doc.customer and frappe.get_meta(T).has_field("customer"):
            or_filters.append([T, "customer", "=", doc.customer])
        try:
            rows = frappe.get_list(T, or_filters=or_filters, fields=helpdesk_agent._fields(), order_by="modified desc",
                                   limit_page_length=10)
            tickets_out = [helpdesk_agent.ticket_summary(r) for r in rows]
        except frappe.PermissionError:
            tickets_out = []
    return {"conversations": convs, "tickets": tickets_out}


@frappe.whitelist(methods=["GET"])
def live(name: str):
    """Cheap state for the open conversation: customer typing, visitor online, assistant drafting."""
    _conv(name)
    from thinknxg_support.api.v1.agent import _live_state

    return _live_state(name)


@frappe.whitelist(methods=["POST"])
def typing(name: str):
    _conv(name)
    from thinknxg_support.integrations import realtime

    first = (frappe.db.get_value("User", frappe.session.user, "first_name") or "").strip()
    realtime.set_typing(name, "agent", first or "1")
    realtime.heartbeat(frappe.session.user)
    return {"ok": True}


@frappe.whitelist(methods=["POST"])
def heartbeat():
    """The app is open: count the agent as online for routing and the transfer list."""
    staff_auth.require_staff()
    from thinknxg_support.integrations import realtime

    realtime.heartbeat(frappe.session.user)
    return {"ok": True}


# ------------------------------------------------------------------ alerts and push for the apps
@frappe.whitelist(methods=["GET"])
def alert_config():
    """Team alert rules merged with this agent's preferences (sound, repeat until acknowledged, volume, mute)."""
    staff_auth.require_staff()
    from thinknxg_support.integrations import alerts as al

    return al.config()


# ------------------------------------------------------------------ link customer, create ticket, saved replies
@frappe.whitelist(methods=["GET"])
def customer_search(q: str = "", conversation: str | None = None):
    """Customers to link a chat to: name, ID, e-mail or phone. Staff only; returns names, not records. With a
    conversation, customers whose contacts match the visitor's e-mail or phone come first."""
    staff_auth.require_staff()
    q = strip_html(q or "").strip()[:80]
    like = f"%{q}%"
    rows = frappe.get_all("Customer", filters={"disabled": 0},
                          or_filters=[["customer_name", "like", like], ["name", "like", like], ["email_id", "like", like],
                                      ["mobile_no", "like", like]] if q else None,
                          fields=["name", "customer_name", "email_id", "mobile_no", "customer_type"],
                          order_by="modified desc", limit_page_length=20)
    suggested = []
    if conversation:
        doc = _conv(conversation)
        email = doc.get("guest_email")
        phone = doc.get("guest_phone") or (doc.get("whatsapp_number") and f"%{doc.whatsapp_number[-8:]}")
        cond, args = [], []
        if email:
            cond.append("c.email_id = %s")
            args.append(email)
        if phone:
            cond.append("(c.mobile_no like %s or c.phone like %s)")
            args += [phone if "%" in phone else f"%{phone[-8:]}", phone if "%" in phone else f"%{phone[-8:]}"]
        if cond:
            suggested = frappe.db.sql_list(f"""select distinct dl.link_name from `tabContact` c
                join `tabDynamic Link` dl on dl.parent = c.name and dl.parenttype = 'Contact' and dl.link_doctype = 'Customer'
                where {' or '.join(cond)} limit 5""", args)
    seen, out = set(), []
    for name in suggested:
        r = frappe.db.get_value("Customer", name, ["name", "customer_name", "email_id", "mobile_no", "customer_type"], as_dict=True)
        if r and r.name not in seen:
            seen.add(r.name)
            out.append({**r, "suggested": True})
    for r in rows:
        if r.name not in seen:
            seen.add(r.name)
            out.append({**r, "suggested": False})
    return out


@frappe.whitelist(methods=["GET"])
def customer_contacts(customer: str):
    staff_auth.require_staff()
    if not frappe.db.exists("Customer", customer):
        raise frappe.DoesNotExistError(_("Customer not found."))
    names = frappe.get_all("Dynamic Link", filters={"parenttype": "Contact", "link_doctype": "Customer", "link_name": customer},
                           pluck="parent")
    return [{"name": c.name, "full_name": " ".join(x for x in (c.first_name, c.last_name) if x) or c.name,
             "email": c.email_id, "phone": c.mobile_no or c.phone}
            for c in frappe.get_all("Contact", filters={"name": ["in", names or [""]]},
                                    fields=["name", "first_name", "last_name", "email_id", "mobile_no", "phone"])]


@frappe.whitelist(methods=["POST"])
def link_customer(name: str, customer: str, contact: str | None = None, create_contact: int = 0):
    """Attach the chat to an existing customer (and contact). With create_contact, the visitor's name, e-mail and
    phone become a new contact of that customer. The customer is registered as an HD Customer."""
    doc = _conv(name, "write")
    if create_contact and not contact:
        contact = _contact_from_visitor(doc, customer)
    from thinknxg_support.thinknxg_support.doctype.support_conversation_link.support_conversation_link import (
        link_customer as _link,
    )

    _link(name, customer, contact)
    from thinknxg_support.integrations import helpdesk

    try:
        helpdesk.sync_hd_customer(customer)
    except Exception:
        frappe.log_error(title="thinkNXG Support: HD Customer sync on link failed")
    return conversation_detail(frappe.get_doc(CONV, name))


def _contact_from_visitor(doc, customer: str) -> str:
    email = (doc.get("guest_email") or "").strip()
    phone = (doc.get("guest_phone") or (f"+{doc.whatsapp_number}" if doc.get("whatsapp_number") else "")).strip()
    if email:
        existing = frappe.db.get_value("Contact", {"email_id": email})
        if existing:
            if not frappe.db.exists("Dynamic Link", {"parenttype": "Contact", "parent": existing,
                                                     "link_doctype": "Customer", "link_name": customer}):
                c = frappe.get_doc("Contact", existing)
                c.append("links", {"link_doctype": "Customer", "link_name": customer})
                c.save(ignore_permissions=True)
            return existing
    full = (doc.get("guest_name") or doc.get("whatsapp_profile_name") or email or phone or _("Visitor")).strip()
    first, _sp, last = full.partition(" ")
    c = frappe.get_doc({"doctype": "Contact", "first_name": first[:140], "last_name": last[:140] or None,
                        "links": [{"link_doctype": "Customer", "link_name": customer}]})
    if email:
        c.append("email_ids", {"email_id": email, "is_primary": 1})
    if phone:
        c.append("phone_nos", {"phone": phone, "is_primary_mobile_no": 1})
    c.insert(ignore_permissions=True)
    return c.name


@frappe.whitelist(methods=["GET"])
def ticket_options():
    """Values for the Create ticket form (Helpdesk's own lists)."""
    hd = _hd()
    types = frappe.get_all("HD Ticket Type", pluck="name") if frappe.db.exists("DocType", "HD Ticket Type") else []
    return {"priorities": hd.priorities(), "teams": hd.teams(), "ticket_types": types}


@frappe.whitelist(methods=["POST"])
def create_ticket(name: str, client_request_id: str, subject: str | None = None, priority: str | None = None,
                  team: str | None = None, ticket_type: str | None = None, reply: str | None = None):
    """Create a Helpdesk ticket from this chat (the transcript goes in the description, the chat is linked to it).
    Optional first reply to the customer through Helpdesk's e-mail workflow. Retry-safe."""
    doc = _conv(name, "write")
    hd = _hd()
    if doc.helpdesk_ticket:
        return {"ticket": doc.helpdesk_ticket, "duplicate": True}

    def run():
        from thinknxg_support.integrations import conversations

        if subject and subject.strip() and subject.strip() != doc.subject:
            doc.db_set("subject", strip_html(subject).strip()[:140], update_modified=False)
            doc.reload()
        ticket = conversations.escalate_to_ticket(doc, actor="agent")
        values = {k: v for k, v in (("priority", priority), ("agent_group", team), ("ticket_type", ticket_type)) if v}
        t = frappe.get_doc("HD Ticket", ticket)
        meta = t.meta
        values = {k: v for k, v in values.items() if meta.has_field(k)}
        if values:
            t.update(values)
            t.flags.ignore_permissions = True
            t.save()
        try:
            hd.assign(ticket, frappe.session.user)
        except Exception:
            pass  # assignment is a convenience; the ticket exists
        if reply and reply.strip():
            hd.reply(ticket, _text_html(reply))
        return {"ticket": str(ticket)}

    return _once(client_request_id, "create_ticket", name, run)


@frappe.whitelist(methods=["GET"])
def saved_replies(q: str = "", ticket: str | None = None):
    """Helpdesk saved replies this agent may use (Helpdesk permissions and scope: global, my teams, my own)."""
    _hd()
    dt = "HD Saved Reply" if frappe.db.exists("DocType", "HD Saved Reply") else (
        "HD Canned Response" if frappe.db.exists("DocType", "HD Canned Response") else None)
    if not dt:
        return []
    meta = frappe.get_meta(dt)
    body = "message" if meta.has_field("message") else "content"
    fields = ["name", "title", body, "owner"] + (["scope"] if meta.has_field("scope") else [])
    q = strip_html(q or "").strip()[:80]
    rows = frappe.get_list(dt, fields=fields, or_filters=[[dt, "title", "like", f"%{q}%"], [dt, body, "like", f"%{q}%"]] if q else None,
                           order_by="title asc", limit_page_length=200)
    user = frappe.session.user
    my_teams = set()
    if meta.has_field("scope"):
        for child in ("HD Team Item", "HD Team Member"):
            if frappe.db.exists("DocType", child):
                my_teams = set(frappe.get_all(child, filters={"user": user, "parenttype": "HD Team"}, pluck="parent"))
                break
    out = []
    for r in rows:
        scope = r.get("scope") or "Global"
        if scope == "Personal" and r.owner != user:
            continue
        if scope == "Team" and frappe.db.exists("DocType", "HD Saved Reply Team"):
            teams = set(frappe.get_all("HD Saved Reply Team", filters={"parent": r.name}, pluck="team"))
            if teams and not teams & my_teams and not staff_auth.is_manager():
                continue
        out.append({"name": r.name, "title": r.title, "scope": scope, "preview": plain_text(r.get(body) or "")[:200]})
    return out


@frappe.whitelist(methods=["POST"])
def saved_reply_render(name: str, ticket: str | None = None, conversation: str | None = None):
    """A saved reply rendered the way Helpdesk renders it (ticket and agent fields filled in)."""
    hd = _hd()
    if ticket:
        hd.get_ticket(ticket)
        try:
            from helpdesk.api.saved_replies import get_rendered_saved_reply

            html = get_rendered_saved_reply(ticket, name).get("message") or ""
            return {"html": html, "text": plain_text(html)}
        except ImportError:
            pass
    dt = "HD Saved Reply" if frappe.db.exists("DocType", "HD Saved Reply") else "HD Canned Response"
    r = frappe.get_doc(dt, name)
    r.check_permission("read")
    context = frappe.get_doc("User", frappe.session.user).as_dict()
    if ticket:
        context = {**frappe.get_doc("HD Ticket", ticket).as_dict(), **context}
    elif conversation:
        c = _conv(conversation)
        context = {"subject": c.subject, "raised_by": c.get("guest_email"), "customer": c.customer, **context}
    # templates are written by agents, as in Helpdesk
    html = frappe.render_template(r.get("message") or r.get("content") or "", context)  # nosemgrep
    return {"html": html, "text": plain_text(html)}


@frappe.whitelist(methods=["POST"])
def send_test_alert(kind: str = "New Chat"):
    """A real alert through the server, the same way chats and tickets raise them (checks sound end to end)."""
    staff_auth.require_staff()
    from thinknxg_support.integrations import alerts as al

    return {"message": al.send_test(kind)}


@frappe.whitelist(methods=["POST"])
def send_test_push():
    """Send this agent a test push to each registered device (generic text, like every push)."""
    staff_auth.require_staff()
    from thinknxg_support.integrations import push

    return push.send_to_users([frappe.session.user], {"kind": "Test"}, now=True)
