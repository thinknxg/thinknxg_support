"""One alert centre for support agents.

Activities (KINDS) raise alerts for the right agents. The desk shows each alert as a pop-up with a sound; repeating
alerts keep sounding until the agent acknowledges them or the work is picked up (the chat is assigned or answered,
the ticket is assigned or replied to, the escalation is taken). Every alert that needs acknowledging is stored in
Support Agent Alert with when it was acknowledged, so response to alerts can be measured.

Team defaults live in Support Alert Settings; each agent can override them in their Support Alert Preference.
Alert hooks never break the chat, ticket or message that triggered them.
"""
from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import add_to_date, cint, now_datetime, strip_html, time_diff_in_seconds

ALERT = "Support Agent Alert"
CONV = "Support Conversation Link"
EVENT = "thinknxg_support_alert"
CLEAR = "thinknxg_support_alert_clear"
KINDS = ['New Chat', 'Chat Message', 'New Ticket', 'Ticket Assigned', 'Conversation Message', 'Escalation', 'Negative Feedback', 'Positive Feedback']
EPHEMERAL = {"Chat Message", "Conversation Message", "Positive Feedback"}  # not stored unless the team makes them repeat
DEFAULTS = {k: {"enabled": 1, "popup": 1, "sound": s, "repeat_until_ack": r, "repeat_seconds": sec, "max_repeats": mx,
                "desktop_notification": d, "volume": v, "custom_sound": None}
            for k, s, r, sec, mx, d, v in [('New Chat', 'Ring', 1, 10, 0, 1, 90), ('Chat Message', 'Ping', 0, 0, 0, 1, 70), ('New Ticket', 'Chime', 1, 60, 3, 1, 80), ('Ticket Assigned', 'Bell', 1, 30, 5, 1, 80), ('Conversation Message', 'Pop', 0, 0, 0, 1, 70), ('Escalation', 'Siren', 1, 15, 0, 1, 100), ('Negative Feedback', 'Knock', 0, 0, 0, 1, 80), ('Positive Feedback', 'Chime', 0, 0, 0, 0, 60)]}


def _safe(fn):
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception:
            frappe.log_error(title=f"thinkNXG Support: alert {fn.__name__} failed")
            return None
    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper


def _settings():
    if not frappe.db.exists("DocType", "Support Alert Settings"):
        return None
    return frappe.get_cached_doc("Support Alert Settings")


def rules() -> dict:
    out = {k: dict(v) for k, v in DEFAULTS.items()}
    s = _settings()
    for r in (s.rules if s else []):
        if r.kind in out:
            out[r.kind].update({"enabled": cint(r.enabled), "popup": cint(r.popup), "sound": r.sound or "None",
                                "repeat_until_ack": cint(r.repeat_until_ack), "repeat_seconds": max(5, cint(r.repeat_seconds) or 15),
                                "max_repeats": cint(r.max_repeats), "desktop_notification": cint(r.desktop_notification),
                                "volume": cint(r.volume), "custom_sound": r.custom_sound})
    return out


def agent_roles() -> list[str]:
    s = _settings()
    text = (s.agent_roles if s else None) or "Support Agent\nSupport Manager\nAgent\nAgent Manager"
    return [r.strip() for r in text.splitlines() if r.strip()]


def is_agent(user: str | None) -> bool:
    if not user or user == "Guest":
        return False
    if user == "Administrator":
        return True  # has every role; often the account used to try things out
    row = frappe.db.get_value("User", user, ["enabled", "user_type"], as_dict=True)
    if not (row and row.enabled and row.user_type == "System User"):
        return False
    return bool(set(agent_roles()) & set(frappe.get_roles(user)))


def all_agents() -> list[str]:
    users = frappe.get_all("Has Role", filters={"role": ["in", agent_roles()], "parenttype": "User"}, pluck="parent",
                           distinct=True)
    users = [u for u in users if u != "Administrator" and is_agent(u)]
    return users or ["Administrator"]  # nobody has an agent role yet: at least the administrator hears it


def queue_members(queue: str | None) -> list[str]:
    if not queue or not frappe.db.exists("Support Chat Queue", queue):
        return []
    return [m.user for m in frappe.get_cached_doc("Support Chat Queue", queue).members if m.active and is_agent(m.user)]


# ------------------------------------------------------------------ raise / clear
def raise_alert(kind: str, users, title: str, body: str = "", *, reference_doctype: str | None = None,
                reference_name: str | None = None, route: str | None = None, group_key: str | None = None,
                priority: str | None = None, lines: list[str] | None = None, once: bool = False):
    """Alert these agents. Repeating kinds are stored (once per user and group while open) and sent to the desk.
    once=True: a single sound, not stored (e.g. a chat the assistant is answering)."""
    rule = rules().get(kind)
    if not rule or not rule["enabled"]:
        return
    users = [u for u in dict.fromkeys(users or []) if is_agent(u)]
    if not users:
        return
    store = (kind not in EPHEMERAL or rule["repeat_until_ack"]) and not once
    now = now_datetime()
    base = {"kind": kind, "title": (title or "")[:140], "body": strip_html(body or "")[:500], "lines": lines or [],
            "reference_doctype": reference_doctype, "reference_name": reference_name, "route": route,
            "group_key": group_key, "priority": priority, "alerted_on": str(now), "stored": store, "once": bool(once)}
    for u in users:
        payload = dict(base)
        if store:
            existing = frappe.db.get_value(ALERT, {"user": u, "group_key": group_key, "status": "Open"}, "name") if group_key else None
            if existing:
                continue  # already sounding for this person
            doc = frappe.get_doc({"doctype": ALERT, "user": u, "kind": kind, "status": "Open", "title": base["title"],
                                  "body": "\n".join([base["body"], *base["lines"]]).strip()[:2000],
                                  "reference_doctype": reference_doctype, "reference_name": reference_name, "route": route,
                                  "group_key": group_key, "priority": priority, "alerted_on": now})
            doc.insert(ignore_permissions=True)
            payload["id"] = doc.name
        else:
            payload["id"] = f"e:{group_key or kind}:{frappe.generate_hash(length=8)}"
        frappe.publish_realtime(EVENT, payload, user=u, after_commit=True)


def clear(group_key: str, reason: str, *, keep: list[str] | None = None, prefix: bool = False):
    """Stop an alert for everyone (except `keep`), e.g. when the chat was assigned or answered."""
    if not group_key or not frappe.db.exists("DocType", ALERT):
        return
    filters = {"status": "Open", "group_key": ["like", group_key + "%"] if prefix else group_key}
    rows = frappe.get_all(ALERT, filters=filters, fields=["name", "user", "group_key"], limit=500)
    by_user = {}
    for r in rows:
        if keep and r.user in keep:
            continue
        frappe.db.set_value(ALERT, r.name, {"status": "Handled", "handled_reason": reason[:140]}, update_modified=False)
        by_user.setdefault(r.user, []).append(r.name)
    # tell every open desk, also for alerts that were never stored (chat messages)
    targets = set(by_user) | ({frappe.session.user} if frappe.session.user not in ("Guest", "Administrator") else set())
    for u in targets:
        frappe.publish_realtime(CLEAR, {"ids": by_user.get(u, []), "group": group_key, "prefix": prefix}, user=u, after_commit=True)
    if not keep:
        frappe.publish_realtime(CLEAR, {"ids": [], "group": group_key, "prefix": prefix}, doctype=CONV, after_commit=True)


# ------------------------------------------------------------------ desk API
def _require_agent():
    if not is_agent(frappe.session.user) and "System Manager" not in frappe.get_roles():
        frappe.throw(_("Only support agents get alerts."), frappe.PermissionError)


def my_preference():
    name = frappe.db.get_value("Support Alert Preference", {"user": frappe.session.user})
    return frappe.get_doc("Support Alert Preference", name) if name else None


@frappe.whitelist(methods=["GET"])
def config():
    """Team rules merged with this agent's own preferences, for the desk alert centre."""
    if not (is_agent(frappe.session.user) or "System Manager" in frappe.get_roles()):
        return {"enabled": False}
    r = rules()
    pref = my_preference()
    out_prefs = {"mute_all": 0, "volume": 80, "desktop_notifications": 1, "items": {}}
    if pref:
        out_prefs.update({"mute_all": cint(pref.mute_all), "volume": cint(pref.volume),
                          "desktop_notifications": cint(pref.desktop_notifications)})
        for i in pref.items:
            out_prefs["items"][i.kind] = {"sound": i.sound, "popup": i.popup, "repeat": i.repeat}
    return {"enabled": True, "is_agent": is_agent(frappe.session.user), "rules": r, "prefs": out_prefs,
            "expire_hours": cint((_settings() or {}).get("expire_hours")) or 24}


@frappe.whitelist(methods=["GET"])
def diagnose():
    """Why this user may not hear alerts: roles and team rules (the browser checks the rest)."""
    r = rules()
    return {"is_agent": is_agent(frappe.session.user), "agent_roles": agent_roles(),
            "enabled_kinds": [k for k, v in r.items() if v["enabled"]], "user": frappe.session.user}


@frappe.whitelist(methods=["POST"])
def send_test(kind: str = "New Chat"):
    """Send yourself a real alert through the server, the same way chats and tickets do."""
    if kind not in KINDS:
        frappe.throw(_("Unknown activity."))
    if not is_agent(frappe.session.user):
        return _("No alert sent: {0} does not have an agent role ({1}). Alerts only go to agents.").format(
            frappe.session.user, ", ".join(agent_roles()))
    if not rules()[kind]["enabled"]:
        return _("No alert sent: {0} alerts are switched off in Support Alert Settings.").format(_(kind))
    raise_alert(kind, [frappe.session.user], _("Test alert: {0}").format(_(kind)),
                _("If you heard the {0} sound, alerts work in this browser.").format(_(rules()[kind]["sound"])),
                group_key=f"test:{frappe.session.user}:{frappe.generate_hash(length=6)}", route=None)
    return _("Test alert sent. It should appear within a few seconds (15 at most if live updates are off).")


@frappe.whitelist(methods=["GET"])
def my_alerts():
    if not is_agent(frappe.session.user):
        return []
    rows = frappe.get_all(ALERT, filters={"user": frappe.session.user, "status": "Open"},
                          fields=["name", "kind", "title", "body", "reference_doctype", "reference_name", "route", "group_key",
                                  "priority", "alerted_on"], order_by="alerted_on desc", limit=20)
    return [{"id": r.name, "kind": r.kind, "title": r.title, "body": r.body or "", "lines": [],
             "reference_doctype": r.reference_doctype, "reference_name": r.reference_name, "route": r.route,
             "group_key": r.group_key, "priority": r.priority, "alerted_on": str(r.alerted_on), "stored": True,
             "replay": True} for r in rows]


@frappe.whitelist(methods=["POST"])
def acknowledge(ids):
    """The agent saw it. Only their own alerts; records how long it took."""
    ids = frappe.parse_json(ids) if isinstance(ids, str) and ids.startswith("[") else ([ids] if isinstance(ids, str) else ids)
    now = now_datetime()
    done = []
    for name in ids or []:
        if not isinstance(name, str) or name.startswith("e:"):
            continue
        row = frappe.db.get_value(ALERT, name, ["user", "status", "alerted_on"], as_dict=True)
        if not row or row.user != frappe.session.user or row.status != "Open":
            continue
        frappe.db.set_value(ALERT, name, {"status": "Acknowledged", "acknowledged_on": now,
                                          "ack_seconds": round(time_diff_in_seconds(now, row.alerted_on), 1)},
                            update_modified=False)
        done.append(name)
    if done:
        frappe.publish_realtime(CLEAR, {"ids": done}, user=frappe.session.user, after_commit=True)
    return done


@frappe.whitelist(methods=["POST"])
def open_my_preferences():
    """Create this agent's preference record on first use and return its name."""
    _require_agent()
    pref = my_preference()
    if pref:
        return pref.name
    doc = frappe.get_doc({"doctype": "Support Alert Preference", "user": frappe.session.user})
    doc.insert(ignore_permissions=True)
    return doc.name


# ------------------------------------------------------------------ activities
def _chat_label(conv) -> str:
    if conv.get("channel") == "WhatsApp":
        who = conv.get("whatsapp_profile_name") or ("+" + (conv.get("whatsapp_number") or ""))
    elif conv.get("is_guest"):
        who = conv.get("guest_name") or _("Visitor")
    else:
        who = frappe.db.get_value("Customer", conv.get("customer"), "customer_name") if conv.get("customer") else None
        who = who or frappe.db.get_value("User", conv.get("started_by"), "full_name") or conv.get("subject")
    return who or _("Customer")


def _last_inbound(conv_name: str) -> str:
    rows = frappe.get_all("Support Portal Message", filters={"conversation": conv_name, "direction": "Inbound"},
                          fields=["content"], order_by="creation desc", limit=1)
    return strip_html(rows[0].content)[:200] if rows else ""


def _chat_route(conv_name: str) -> str:
    return f"support-chat?conversation={conv_name}"


@_safe
def on_new_chat(conv, reason: str | None = None):
    """A chat now needs a person: ring the assigned agent, or the queue's members until someone takes it."""
    conv = frappe.get_doc(CONV, conv.name) if not isinstance(conv, str) else frappe.get_doc(CONV, conv)
    if conv.get("channel") not in ("Live Chat", "WhatsApp"):
        return on_customer_message(conv)  # a new portal conversation is a conversation message
    users = [conv.assigned_agent] if conv.get("assigned_agent") else queue_members(conv.get("queue"))
    if not users:
        from thinknxg_support.integrations import routing

        q = routing.pick_queue(conv.get("channel"))
        users = queue_members(q.name) if q else []
    users = users or all_agents()
    raise_alert("New Chat", users, _("New chat: {0}").format(_chat_label(conv)), _last_inbound(conv.name),
                reference_doctype=CONV, reference_name=conv.name, route=_chat_route(conv.name),
                group_key=f"chat:{conv.name}", lines=[x for x in (conv.get("channel"), reason) if x])


@_safe
def on_assistant_chat(conv):
    """A new chat the assistant is answering: one New Chat sound for the team (no repeat). If the assistant hands
    it over, the usual ringing alert follows."""
    s = _settings()
    if not s or not cint(s.get("alert_assistant_chats")) or conv.get("channel") not in ("Live Chat", "WhatsApp"):
        return
    from thinknxg_support.integrations import routing

    q = routing.pick_queue(conv.get("channel"))
    users = (queue_members(q.name) if q else []) or all_agents()
    raise_alert("New Chat", users, _("New chat (assistant answering): {0}").format(_chat_label(conv)), _last_inbound(conv.name),
                reference_doctype=CONV, reference_name=conv.name, route=_chat_route(conv.name),
                group_key=f"botchat:{conv.name}", once=True)


@_safe
def on_chat_assigned(conv, agent: str | None):
    """Someone has the chat: stop ringing the others; the assignee keeps an alert unless they took it themselves."""
    group = f"chat:{conv.name}"
    if not agent:
        return
    if agent == frappe.session.user:
        clear(group, _("Taken by {0}").format(agent))
        return
    clear(group, _("Assigned to {0}").format(agent), keep=[agent])
    raise_alert("New Chat", [agent], _("Chat assigned to you: {0}").format(_chat_label(conv)), _last_inbound(conv.name),
                reference_doctype=CONV, reference_name=conv.name, route=_chat_route(conv.name), group_key=group)


@_safe
def on_customer_message(conv, first: bool = False):
    if first or conv.get("handling") == "Bot":
        return
    chat = conv.get("channel") in ("Live Chat", "WhatsApp")
    kind = "Chat Message" if chat else "Conversation Message"
    users = [conv.assigned_agent] if conv.get("assigned_agent") else queue_members(conv.get("queue"))
    if not users and not chat:
        users = all_agents()
    raise_alert(kind, users, (_("New message from {0}") if chat else _("Customer replied: {0}")).format(_chat_label(conv)),
                _last_inbound(conv.name), reference_doctype=CONV, reference_name=conv.name,
                route=_chat_route(conv.name) if chat else f"support-conversation-link/{conv.name}",
                group_key=f"msg:{conv.name}")


@_safe
def on_agent_reply(conv_name: str):
    clear(f"chat:{conv_name}", _("Answered"))
    clear(f"msg:{conv_name}", _("Answered"))


@_safe
def on_conversation_closed(conv_name: str):
    clear(f"chat:{conv_name}", _("Chat closed"))
    clear(f"msg:{conv_name}", _("Chat closed"))


def _hd_team_users(team: str | None) -> list[str]:
    if not team or not frappe.db.exists("DocType", "HD Team"):
        return []
    for child in ("HD Team Item", "HD Team Member"):
        if frappe.db.exists("DocType", child):
            users = frappe.get_all(child, filters={"parent": team, "parenttype": "HD Team"}, pluck="user")
            return [u for u in users if is_agent(u)]
    return []


def _assignees(doc) -> list[str]:
    try:
        return json.loads(doc.get("_assign") or "[]")
    except ValueError:
        return []


@_safe
def on_hd_ticket(doc, method=None):
    new = method == "after_insert"
    route = f"/helpdesk/tickets/{doc.name}"
    label = f"#{doc.name} {doc.get('subject') or ''}".strip()
    if new:
        users = _assignees(doc) or _hd_team_users(doc.get("agent_group")) or all_agents()
        raise_alert("New Ticket", users, _("New ticket: {0}").format(label), doc.get("description") or "",
                    reference_doctype="HD Ticket", reference_name=doc.name, route=route, group_key=f"ticket:{doc.name}",
                    priority=doc.get("priority"), lines=[x for x in (doc.get("raised_by"), doc.get("priority")) if x])
        return
    if doc.has_value_changed("_assign"):
        before = doc.get_doc_before_save()
        old = set(_assignees(before)) if before else set()
        new_users = [u for u in _assignees(doc) if u not in old]
        if _assignees(doc):
            clear(f"ticket:{doc.name}", _("Assigned"))
        for u in new_users:
            if u != frappe.session.user:
                raise_alert("Ticket Assigned", [u], _("Ticket assigned to you: {0}").format(label), doc.get("description") or "",
                            reference_doctype="HD Ticket", reference_name=doc.name, route=route,
                            group_key=f"tassign:{doc.name}:{u}", priority=doc.get("priority"))
    if doc.has_value_changed("status") and doc.get("status") not in ("Open",):
        clear(f"ticket:{doc.name}", _("Status {0}").format(doc.get("status")))
        if doc.get("status") in ("Resolved", "Closed"):
            clear(f"tassign:{doc.name}:", _("Ticket {0}").format(doc.get("status")), prefix=True)


@_safe
def on_communication(doc, method=None):
    if doc.reference_doctype != "HD Ticket" or doc.communication_type != "Communication" or doc.sent_or_received != "Sent":
        return
    user = frappe.db.get_value("User", {"email": doc.get("sender"), "user_type": "System User"}) if doc.get("sender") else None
    clear(f"ticket:{doc.reference_name}", _("Replied"))
    if user:
        clear(f"tassign:{doc.reference_name}:{user}", _("Replied"))


@_safe
def on_escalation(doc, reason: str, users: list[str], p: dict):
    """Escalations get their own, distinct alert (the team's Escalation sound)."""
    lines = [f"{p['customer']}" + (f" · {p['customer_details']}" if p.get("customer_details") else ""),
             f"{p['query_type']} · {p['escalation_type']}" + (f" · L{p['level']}" if p.get("level", 1) > 1 else ""),
             f"{_('Assigned to')}: {p['assigned_to']} · {p['escalated_on_label']}"]
    raise_alert("Escalation", users, f"{p['title']}: {p['subject']}", p.get("description") or "",
                reference_doctype="Support Escalation", reference_name=doc.name, route=f"support-escalation/{doc.name}",
                group_key=f"esc:{doc.name}:{reason}", priority=p.get("priority"), lines=lines)


@_safe
def on_escalation_taken(name: str, reason: str):
    clear(f"esc:{name}:", reason, prefix=True)


# ------------------------------------------------------------------ housekeeping
def expire_and_purge():
    s = _settings()
    hours = cint(s.expire_hours) if s else 24
    keep = cint(s.keep_days) if s else 90
    cutoff = add_to_date(now_datetime(), hours=-(hours or 24))
    for name in frappe.get_all(ALERT, filters={"status": "Open", "alerted_on": ["<", cutoff]}, pluck="name", limit=5000):
        frappe.db.set_value(ALERT, name, {"status": "Expired", "handled_reason": _("Not acknowledged in time")},
                            update_modified=False)
    if keep:
        frappe.db.delete(ALERT, {"creation": ["<", add_to_date(now_datetime(), days=-keep)]})
