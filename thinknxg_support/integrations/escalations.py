"""Escalated support queries: one Support Escalation per escalated chat, conversation or ticket.

Triggers call `raise_escalation`; activity on the source (agent reply, customer message, close) calls `on_activity`.
Notifications go out after the transaction commits, through the channels switched on in Support Escalation Settings:
an in-app pop-up (realtime), the notification center, email and WhatsApp. Escalations never block the chat or ticket
that raised them: every trigger is wrapped so a failure here is logged and the customer flow carries on.
"""
from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import add_to_date, cint, get_datetime, get_url, now_datetime, strip_html, time_diff_in_seconds

ESC = "Support Escalation"
CONV = "Support Conversation Link"
OPEN = ("New", "Pending", "In Progress")
PRIORITY_RANK = {"Critical": 4, "High": 3, "Medium": 2, "Low": 1}
DEFAULT_TARGETS = {"Critical": (15, 240), "High": (30, 480), "Medium": (120, 1440), "Low": (480, 4320)}
HD_PRIORITY = {"urgent": "Critical", "critical": "Critical", "high": "High", "medium": "Medium", "low": "Low"}
EVENT = "thinknxg_support_escalation"
STAFF_ROLES = {"Support Agent", "Support Manager", "Support Portal Administrator", "System Manager"}


def settings():
    return frappe.get_cached_doc("Support Escalation Settings")


def enabled() -> bool:
    try:
        return bool(frappe.db.exists("DocType", ESC) and settings().enabled)
    except Exception:
        return False


def _safe(fn):
    """Escalation hooks must never break a chat, a ticket save or a customer message."""
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception:
            frappe.log_error(title=f"thinkNXG Support: escalation {fn.__name__} failed")
            return None
    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper


# ------------------------------------------------------------------ record helpers
def targets(priority: str) -> tuple[int, int]:
    for t in settings().targets or []:
        if t.priority == priority:
            return cint(t.response_minutes), cint(t.resolution_minutes)
    return DEFAULT_TARGETS.get(priority, DEFAULT_TARGETS["Medium"])


def _log(doc, action: str, details: str = "", user: str | None = None):
    doc.append("log", {"logged_on": now_datetime(), "action": action[:140], "details": (details or "")[:1000],
                       "by_user": user or frappe.session.user})


def on_validate(doc):
    """Keep due times, overdue flags and 'pending response' consistent whatever changed the record."""
    if not doc.escalated_on:
        doc.escalated_on = now_datetime()
    if doc.is_new() or doc.has_value_changed("priority"):
        resp, resol = targets(doc.priority or "Medium")
        doc.response_due = add_to_date(doc.escalated_on, minutes=resp)
        doc.resolution_due = add_to_date(doc.escalated_on, minutes=resol)
    if doc.status == "New" and doc.assigned_to:
        doc.status = "Pending"
    if doc.status in ("Resolved", "Closed"):
        doc.resolved_on = doc.resolved_on or now_datetime()
        if not doc.resolution_minutes:
            doc.resolution_minutes = round(time_diff_in_seconds(doc.resolved_on, doc.escalated_on) / 60, 1)
        if doc.status == "Closed":
            doc.closed_on = doc.closed_on or now_datetime()
        doc.awaiting_reply = 0
        doc.overdue = 0
    else:
        doc.resolved_on = None
        doc.resolution_minutes = None
        doc.closed_on = None
        now = now_datetime()
        doc.response_overdue = 1 if (not doc.first_response_on and doc.response_due and get_datetime(doc.response_due) < now) else 0
        doc.resolution_overdue = 1 if (doc.resolution_due and get_datetime(doc.resolution_due) < now) else 0
        doc.overdue = 1 if (doc.response_overdue or doc.resolution_overdue) else 0
    doc.needs_response = 1 if (doc.status in ("New", "Pending") or (doc.status == "In Progress" and doc.awaiting_reply)) else 0
    for n in doc.notes:
        n.by_user = n.by_user or frappe.session.user
        n.noted_on = n.noted_on or now_datetime()


def on_record_update(doc):
    """Keep the Frappe assignment (ToDo) in step with Assigned To."""
    if doc.has_value_changed("assigned_to"):
        before = doc.get_doc_before_save()
        old = before.assigned_to if before else None
        _sync_todo(doc, old, doc.assigned_to)
    if doc.has_value_changed("status") and doc.status in ("Resolved", "Closed"):
        _close_todos(doc.name, "Closed")
    if doc.has_value_changed("status") and doc.status in ("In Progress", "Resolved", "Closed"):
        from thinknxg_support.integrations import alerts

        alerts.on_escalation_taken(doc.name, _("Status {0}").format(doc.status))


def _close_todos(name: str, status: str, user: str | None = None):
    filters = {"reference_type": ESC, "reference_name": name, "status": "Open"}
    if user:
        filters["allocated_to"] = user
    for todo in frappe.get_all("ToDo", filters=filters, pluck="name"):
        t = frappe.get_doc("ToDo", todo)
        t.status = status
        t.flags.ignore_permissions = True
        t.save()


def _sync_todo(doc, old: str | None, new: str | None):
    """A ToDo for the assigned person, so the escalation shows in their Assigned To list. Created directly (not via
    assign_to.add) so it also works when a visitor's chat triggered the escalation."""
    try:
        if old and old != new:
            _close_todos(doc.name, "Cancelled", old)
        if new and not frappe.db.exists("ToDo", {"reference_type": ESC, "reference_name": doc.name, "allocated_to": new,
                                                 "status": "Open"}):
            frappe.get_doc({
                "doctype": "ToDo", "allocated_to": new, "reference_type": ESC, "reference_name": doc.name,
                "description": f"{doc.subject} ({doc.query_type})",
                "priority": {"Critical": "High", "High": "High", "Low": "Low"}.get(doc.priority, "Medium"),
                "date": get_datetime(doc.resolution_due).date() if doc.resolution_due else None,
                "assigned_by": frappe.session.user if frappe.session.user != "Guest" else "Administrator",
            }).insert(ignore_permissions=True)
    except Exception:
        frappe.log_error(title="thinkNXG Support: escalation assignment failed")


def open_for(reference_doctype: str, reference_name: str):
    name = frappe.db.get_value(ESC, {"reference_doctype": reference_doctype, "reference_name": reference_name,
                                     "status": ["in", OPEN]}, "name", order_by="creation desc")
    return frappe.get_doc(ESC, name) if name else None


def _least_busy(team: str | None) -> str | None:
    if not team or not frappe.db.exists("Support Chat Queue", team):
        return None
    members = [m.user for m in frappe.get_cached_doc("Support Chat Queue", team).members
               if m.active and frappe.db.get_value("User", m.user, "enabled")]
    if not members:
        return None
    load = {u: frappe.db.count(ESC, {"assigned_to": u, "status": ["in", OPEN]}) for u in members}
    return min(members, key=lambda u: (load[u], members.index(u)))


# ------------------------------------------------------------------ raising
def raise_escalation(query_type: str, escalation_type: str, reference_doctype: str, reference_name: str, *,
                     subject: str, description: str | None = None, customer: str | None = None,
                     customer_name: str | None = None, contact: str | None = None, contact_email: str | None = None,
                     contact_phone: str | None = None, channel: str | None = None, priority: str | None = None,
                     assigned_to: str | None = None, team: str | None = None, related_ticket: str | None = None,
                     note: str | None = None, user: str | None = None):
    """Create an escalation, or, when the query is already escalated, escalate it further if this is a new kind
    of escalation (a repeated trigger of the same kind changes nothing). Returns the Support Escalation."""
    if not enabled():
        return None
    s = settings()
    user = user or frappe.session.user
    existing = open_for(reference_doctype, reference_name)
    if existing:
        if related_ticket and not existing.related_ticket:
            existing.related_ticket = related_ticket
            _log(existing, "Ticket created", related_ticket, user)
            existing.save(ignore_permissions=True)
        if existing.escalation_type == escalation_type and escalation_type != "Manual":
            return existing
        # Escalated again (by hand, or by a different kind of trigger): raise the level. Always return the record.
        escalate_further(existing, priority=priority, note=note or _(escalation_type), user=assigned_to if escalation_type == "Manual" else None,
                         actor=user, kind=escalation_type)
        return frappe.get_doc(ESC, existing.name)
    default_priority = {"Support Chat": s.chat_priority, "Conversation": s.conversation_priority,
                        "Support Ticket": s.ticket_priority}.get(query_type) or "Medium"
    if escalation_type == "SLA Breach":
        default_priority = s.sla_priority or "Critical"
    team = team or (s.default_team if query_type != "Support Chat" else None)
    if not assigned_to and cint(s.auto_assign):
        assigned_to = _least_busy(team)
    if customer and not customer_name:
        customer_name = frappe.db.get_value("Customer", customer, "customer_name")
    doc = frappe.get_doc({
        "doctype": ESC, "query_type": query_type, "escalation_type": escalation_type, "status": "New",
        "priority": priority or default_priority, "subject": (subject or reference_name)[:140],
        "description": (strip_html(description or "") or "")[:2000], "reference_doctype": reference_doctype,
        "reference_name": reference_name, "channel": channel, "customer": customer, "customer_name": customer_name,
        "contact": contact, "contact_email": contact_email, "contact_phone": contact_phone, "assigned_to": assigned_to,
        "team": team, "related_ticket": related_ticket, "escalated_on": now_datetime(), "escalation_level": 1,
    })
    _log(doc, _("Escalated"), f"{_(escalation_type)}" + (f": {note}" if note else ""), user)
    if assigned_to:
        _log(doc, _("Assigned"), assigned_to + (f" ({team})" if team else ""), user)
    doc.insert(ignore_permissions=True)
    from thinknxg_support.audit import log_event

    log_event("Escalation", reference_doctype=ESC, reference_name=doc.name,
              details={"type": escalation_type, "source": f"{reference_doctype} {reference_name}", "priority": doc.priority},
              user=user if user != "Guest" else "Administrator")
    _queue_notify(doc.name, "new")
    return doc


def escalate_further(doc, user: str | None = None, priority: str | None = None, note: str | None = None,
                     actor: str | None = None, kind: str | None = None):
    actor = actor or frappe.session.user
    doc.escalation_level = cint(doc.escalation_level or 1) + 1
    if priority and PRIORITY_RANK.get(priority, 0) > PRIORITY_RANK.get(doc.priority, 0):
        doc.priority = priority
    elif priority and priority != doc.priority and not kind:
        doc.priority = priority  # a person may also lower it deliberately
    if kind:
        doc.escalation_type = kind
    if doc.status in ("Resolved", "Closed"):
        doc.status = "Pending"
    details = (_("Level {0}").format(doc.escalation_level) + (f" · {_(kind)}" if kind else "") +
               (f" · {doc.priority}" if priority else "") + (f": {note}" if note else ""))
    _log(doc, _("Escalated further"), details, actor)
    if user and user != doc.assigned_to:
        _log(doc, _("Reassigned"), f"{doc.assigned_to or '-'} → {user}", actor)
        doc.assigned_to = user
    if note:
        doc.append("notes", {"note": note, "by_user": actor, "noted_on": now_datetime()})
    doc.save(ignore_permissions=True)
    _sync_chat_assignment(doc)
    _queue_notify(doc.name, "further")
    return doc.name


def reassign(doc, user: str, team: str | None = None, note: str | None = None):
    if not frappe.db.get_value("User", user, "enabled"):
        frappe.throw(_("User {0} is disabled or does not exist.").format(user))
    before = doc.assigned_to
    doc.assigned_to = user
    if team is not None:
        doc.team = team or None
    _log(doc, _("Assigned") if not before else _("Reassigned"), f"{before or '-'} → {user}" + (f": {note}" if note else ""))
    if note:
        doc.append("notes", {"note": note})
    doc.save(ignore_permissions=True)
    _sync_chat_assignment(doc)
    if user != frappe.session.user:
        _queue_notify(doc.name, "assigned")
    return doc.name


def set_status(doc, status: str, note: str | None = None, user: str | None = None):
    if status not in ("New", "Pending", "In Progress", "Resolved", "Closed"):
        frappe.throw(_("Unknown status."))
    if status == doc.status:
        return doc.name
    _log(doc, _("Status"), f"{doc.status} → {status}" + (f": {note}" if note else ""), user)
    doc.status = status
    if note:
        doc.append("notes", {"note": note, "by_user": user or frappe.session.user, "noted_on": now_datetime()})
    if status == "In Progress" and not doc.first_response_on:
        _first_response(doc)
    doc.save(ignore_permissions=True)
    return doc.name


def add_note(doc, note: str):
    note = (note or "").strip()
    if not note:
        frappe.throw(_("Write a note first."))
    doc.append("notes", {"note": note[:4000]})
    doc.save(ignore_permissions=True)
    return doc.name


def _first_response(doc, at=None):
    at = at or now_datetime()
    doc.first_response_on = at
    doc.response_minutes = round(time_diff_in_seconds(at, doc.escalated_on) / 60, 1)


def _sync_chat_assignment(doc):
    """Reassigning a chat escalation also hands the chat itself to that person."""
    if doc.reference_doctype != CONV or not doc.assigned_to:
        return
    conv = frappe.get_doc(CONV, doc.reference_name)
    if conv.status == "Closed" or conv.assigned_agent == doc.assigned_to:
        return
    from thinknxg_support.integrations import routing

    routing.assign(conv, doc.assigned_to, conv.queue or doc.team, "Transfer")


# ------------------------------------------------------------------ activity on the source
@_safe
def on_activity(reference_doctype: str, reference_name: str, event: str, user: str | None = None, at=None):
    """event: agent_reply · customer_message · resolved · closed · assigned (user = new assignee)."""
    if not enabled():
        return
    doc = open_for(reference_doctype, reference_name)
    if event == "customer_message" and not doc:
        # A customer writing again after the escalation was resolved reopens it
        name = frappe.db.get_value(ESC, {"reference_doctype": reference_doctype, "reference_name": reference_name,
                                         "status": "Resolved"}, "name", order_by="modified desc")
        if not name:
            return
        doc = frappe.get_doc(ESC, name)
        _log(doc, _("Reopened"), _("The customer wrote again"), "Administrator")
        doc.status = "Pending"
    if not doc:
        return
    at = at or now_datetime()
    if event == "agent_reply":
        if not doc.first_response_on:
            _first_response(doc, at)
            _log(doc, _("First response"), user or "", user)
        doc.awaiting_reply = 0
        if doc.status in ("New", "Pending"):
            doc.status = "In Progress"
        if not doc.assigned_to and user and user not in ("Administrator", "Guest"):
            doc.assigned_to = user
    elif event == "customer_message":
        doc.awaiting_reply = 1
        doc.last_customer_message_on = at
    elif event == "closed" and not doc.first_response_on:
        # The chat ended before anyone answered: keep it open so the team follows up (email, phone).
        _log(doc, _("Chat ended without a reply"), _("Follow up with the customer"), user or "Administrator")
        doc.awaiting_reply = 1
    elif event in ("resolved", "closed"):
        _log(doc, _("Source closed"), f"{reference_doctype} {reference_name}", user or "Administrator")
        doc.status = "Resolved"
    elif event == "assigned" and user and user != doc.assigned_to:
        _log(doc, _("Reassigned"), f"{doc.assigned_to or '-'} → {user}", "Administrator")
        doc.assigned_to = user
    else:
        return
    doc.flags.ignore_permissions = True
    doc.save(ignore_permissions=True)


# ------------------------------------------------------------------ triggers
def _conv_details(conv) -> dict:
    email = conv.get("guest_email")
    phone = conv.get("whatsapp_number") or conv.get("guest_phone")
    if conv.get("contact"):
        c = frappe.db.get_value("Contact", conv.contact, ["email_id", "mobile_no", "phone"], as_dict=True) or {}
        email = email or c.get("email_id")
        phone = phone or c.get("mobile_no") or c.get("phone")
    if not email and conv.get("started_by") and conv.started_by != "Guest":
        email = frappe.db.get_value("User", conv.started_by, "email")
    name = conv.get("guest_name") if conv.get("is_guest") else None
    last = frappe.get_all("Support Portal Message", filters={"conversation": conv.name, "direction": "Inbound"},
                          fields=["content"], order_by="creation desc", limit=1)
    return {"customer": conv.get("customer"), "customer_name": None if conv.get("customer") else (name or email or phone),
            "contact": conv.get("contact"), "contact_email": email, "contact_phone": phone, "channel": conv.get("channel"),
            "description": strip_html(last[0].content)[:500] if last else None}


def _chat_kind(reason: str | None) -> str:
    reason = reason or ""
    if reason == _("Customer asked for a person"):
        return "Customer Asked for Agent"
    if reason.startswith(_("Chatbot rule {0}").split("{0}")[0].strip()):
        return "Chatbot Rule"
    return "AI Handoff"


@_safe
def on_chat_handoff(conv, reason: str, agent: str | None = None, queue: str | None = None):
    if not (enabled() and cint(settings().on_chat_handoff)):
        return
    raise_escalation("Support Chat", _chat_kind(reason), CONV, conv.name, subject=conv.subject or _("Live chat"),
                     assigned_to=agent, team=queue, note=reason, user="Administrator", **_conv_details(conv))


@_safe
def on_direct_chat(conv):
    """A live chat or WhatsApp chat that starts with people (assistant off for it) is an escalation from the start."""
    if not (enabled() and cint(settings().on_direct_live_chat)) or conv.get("channel") not in ("Live Chat", "WhatsApp"):
        return
    from thinknxg_support.integrations import routing

    agent, queue = conv.get("assigned_agent"), conv.get("queue")
    if not agent and cint(settings().auto_assign):
        q = routing.pick_queue(conv.channel)
        agent = routing.pick_agent(q) if q else None
        queue = q.name if q else queue
        if agent:
            routing.assign(conv, agent, queue, "Automatic")
    raise_escalation("Support Chat", "Direct Live Chat", CONV, conv.name, subject=conv.subject or _("Live chat"),
                     assigned_to=agent, team=queue, user="Administrator", **_conv_details(conv))


@_safe
def on_conversation_escalated(conv, ticket: str | None, actor: str | None = None):
    if not (enabled() and cint(settings().on_conversation_escalation)):
        return
    chat = conv.get("channel") in ("Live Chat", "WhatsApp")
    raise_escalation("Support Chat" if chat else "Conversation", "Conversation Escalated", CONV, conv.name,
                     subject=conv.subject or conv.name, related_ticket=ticket, assigned_to=conv.get("assigned_agent"),
                     note=_("Escalated by the customer") if actor == "customer" else None, user=actor or None,
                     **_conv_details(conv))


@_safe
def on_request_escalated(req, ticket: str | None):
    if not (enabled() and cint(settings().on_request_escalation)):
        return
    raise_escalation("Support Ticket", "Request Escalated", "Support Request", req.name, subject=req.subject,
                     description=req.get("details"), customer=req.get("customer"), related_ticket=ticket,
                     contact_email=frappe.db.get_value("User", req.get("raised_by"), "email") if req.get("raised_by") else None,
                     priority={"Urgent": "Critical", "High": "High", "Low": "Low"}.get(req.get("priority") or ""),
                     channel="Service Request")


@_safe
def on_support_request_update(doc, method=None):
    if not doc.has_value_changed("status") or doc.is_new():
        return
    if doc.status == "Completed":
        on_activity("Support Request", doc.name, "resolved")
    elif doc.status == "Cancelled":
        esc = open_for("Support Request", doc.name)
        if esc:
            set_status(esc, "Closed", _("Request cancelled"), user="Administrator")
    if doc.has_value_changed("customer_response") and doc.customer_response:
        on_activity("Support Request", doc.name, "agent_reply", frappe.session.user)


def _hd_priority(value: str | None) -> str | None:
    return HD_PRIORITY.get((value or "").strip().lower())


def _ticket_assignee(doc) -> str | None:
    try:
        users = json.loads(doc.get("_assign") or "[]")
    except ValueError:
        users = []
    return users[0] if users else None


@_safe
def on_hd_ticket(doc, method=None):
    """Helpdesk ticket saved: escalate on an escalation priority or a missed SLA; mirror resolution and assignee."""
    if not enabled():
        return
    s = settings()
    new = method == "after_insert" or doc.is_new()
    common = dict(subject=doc.get("subject") or f"#{doc.name}", description=doc.get("description"),
                  customer=doc.get("customer"), contact=doc.get("contact"), contact_email=doc.get("raised_by"),
                  channel=doc.get("via_customer_portal") and "Helpdesk portal" or "Helpdesk",
                  assigned_to=_ticket_assignee(doc), team=None, related_ticket=doc.name, user="Administrator")
    if cint(s.on_ticket_priority):
        wanted = {p.strip().lower() for p in (s.ticket_priorities or "").splitlines() if p.strip()}
        if (new or doc.has_value_changed("priority")) and (doc.get("priority") or "").strip().lower() in wanted:
            raise_escalation("Support Ticket", "Urgent Ticket", "HD Ticket", doc.name,
                             priority=_hd_priority(doc.get("priority")) or "Critical", **common)
    if cint(s.on_ticket_sla_failed) and not new and doc.has_value_changed("agreement_status") \
            and doc.get("agreement_status") == "Failed":
        raise_escalation("Support Ticket", "SLA Breach", "HD Ticket", doc.name, priority=s.sla_priority or "Critical",
                         note=_("The ticket missed its service level agreement"), **common)
    if not new and doc.has_value_changed("status") and doc.get("status") in ("Resolved", "Closed"):
        on_activity("HD Ticket", doc.name, "resolved")
    if not new and doc.has_value_changed("_assign"):
        who = _ticket_assignee(doc)
        if who:
            on_activity("HD Ticket", doc.name, "assigned", who)


@_safe
def on_communication(doc, method=None):
    if doc.reference_doctype != "HD Ticket" or doc.communication_type != "Communication":
        return
    if doc.sent_or_received == "Sent":
        # Only a person's reply counts as a response, not Helpdesk's automatic acknowledgements
        user = frappe.db.get_value("User", {"email": doc.get("sender"), "user_type": "System User", "enabled": 1}) \
            if doc.get("sender") else None
        if not user and frappe.session.user not in ("Administrator", "Guest") and \
                frappe.db.get_value("User", frappe.session.user, "user_type") == "System User":
            user = frappe.session.user
        if user and user != "Administrator":
            on_activity("HD Ticket", doc.reference_name, "agent_reply", user)
    else:
        on_activity("HD Ticket", doc.reference_name, "customer_message")


@frappe.whitelist(methods=["POST"])
def escalate_document(doctype: str, name: str, priority: str | None = None, note: str | None = None,
                      assign_to: str | None = None):
    """Manual escalation from a chat, conversation, ticket or service request form."""
    if not STAFF_ROLES & set(frappe.get_roles()):
        frappe.throw(_("Only support staff can escalate."), frappe.PermissionError)
    if doctype not in (CONV, "HD Ticket", "Support Request"):
        frappe.throw(_("This document cannot be escalated."))
    src = frappe.get_doc(doctype, name)
    src.check_permission("read")
    if priority and priority not in PRIORITY_RANK:
        frappe.throw(_("Unknown priority."))
    if doctype == CONV:
        chat = src.get("channel") in ("Live Chat", "WhatsApp")
        esc = raise_escalation("Support Chat" if chat else "Conversation", "Manual", CONV, name,
                               subject=src.subject or name, priority=priority, assigned_to=assign_to, note=note,
                               related_ticket=src.get("helpdesk_ticket"), **_conv_details(src))
    elif doctype == "HD Ticket":
        esc = raise_escalation("Support Ticket", "Manual", doctype, name, subject=src.get("subject") or name,
                               description=src.get("description"), customer=src.get("customer"),
                               contact_email=src.get("raised_by"), priority=priority or _hd_priority(src.get("priority")),
                               assigned_to=assign_to or _ticket_assignee(src), related_ticket=name, note=note,
                               channel="Helpdesk")
    else:
        esc = raise_escalation("Support Ticket", "Manual", doctype, name, subject=src.subject, description=src.get("details"),
                               customer=src.get("customer"), priority=priority, assigned_to=assign_to, note=note,
                               related_ticket=src.get("helpdesk_ticket"), channel="Service Request")
    if not esc:
        frappe.throw(_("Escalation tracking is turned off in Support Escalation Settings."))
    return esc.name


# ------------------------------------------------------------------ notifications
def _queue_notify(name: str, reason: str):
    frappe.enqueue("thinknxg_support.integrations.escalations.notify", queue="short", enqueue_after_commit=True,
                   name=name, reason=reason)


REASON_TITLE = {
    "new": "New escalation", "further": "Escalated further", "assigned": "Assigned to you",
    "overdue_response": "Overdue: no first response", "overdue_resolution": "Overdue: not resolved",
}


def _users_with_roles(roles_text: str | None) -> list[str]:
    roles = [r.strip() for r in (roles_text or "").splitlines() if r.strip()]
    if not roles:
        return []
    users = frappe.get_all("Has Role", filters={"role": ["in", roles], "parenttype": "User"}, pluck="parent", distinct=True)
    return [u for u in users if u not in ("Administrator", "Guest")]


def recipients(doc, reason: str) -> list[str]:
    s = settings()
    users = []
    if doc.assigned_to and cint(s.notify_assignee):
        users.append(doc.assigned_to)
    if reason == "assigned":
        return [u for u in users if _is_staff(u)]
    if doc.team and cint(s.notify_team) and frappe.db.exists("Support Chat Queue", doc.team):
        users += [m.user for m in frappe.get_cached_doc("Support Chat Queue", doc.team).members if m.active]
    roles = s.overdue_roles if reason.startswith("overdue") else s.notify_roles
    users += _users_with_roles(roles)
    if not reason.startswith("overdue"):
        users += [u.strip() for u in (s.notify_users or "").splitlines() if u.strip()]
    return [u for u in dict.fromkeys(users) if _is_staff(u)]


def _is_staff(user: str) -> bool:
    row = frappe.db.get_value("User", user, ["enabled", "user_type"], as_dict=True)
    return bool(row and row.enabled and row.user_type == "System User")


def payload(doc, reason: str) -> dict:
    assignee = frappe.utils.get_fullname(doc.assigned_to) if doc.assigned_to else None
    return {
        "name": doc.name, "reason": reason, "title": _(REASON_TITLE.get(reason, "Escalation")),
        "reference": f"{doc.reference_doctype} {doc.reference_name}" if doc.reference_name else doc.name,
        "query_type": doc.query_type, "escalation_type": _(doc.escalation_type or ""), "level": cint(doc.escalation_level),
        "subject": doc.subject, "description": (doc.description or "")[:300],
        "customer": doc.customer_name or doc.customer or _("Visitor"),
        "customer_details": " · ".join(x for x in (doc.contact_email, doc.contact_phone, doc.channel) if x),
        "escalated_on": str(doc.escalated_on), "escalated_on_label": frappe.utils.format_datetime(doc.escalated_on),
        "assigned_to": assignee or _("Unassigned"), "team": doc.team or "", "priority": doc.priority,
        "url": get_url(f"/app/support-escalation/{doc.name}"),
    }


def _email_html(p: dict) -> str:
    esc = frappe.utils.escape_html
    rows = [(_("Reference"), f"{p['name']} · {p['reference']}"), (_("Customer"), p["customer"]),
            (_("Customer details"), p["customer_details"]), (_("Type"), f"{p['query_type']} · {p['escalation_type']}"
                                                              + (f" · {_('level')} {p['level']}" if p["level"] > 1 else "")),
            (_("Subject"), p["subject"]), (_("Escalated on"), p["escalated_on_label"]),
            (_("Assigned to"), p["assigned_to"] + (f" ({p['team']})" if p["team"] else "")), (_("Priority"), p["priority"])]
    color = {"Critical": "#b91c1c", "High": "#c2410c", "Medium": "#1d4ed8", "Low": "#475569"}.get(p["priority"], "#475569")
    body = "".join(f'<tr><td style="padding:6px 12px 6px 0;color:#64748b;white-space:nowrap">{esc(k)}</td>'
                   f'<td style="padding:6px 0">{esc(str(v or "-"))}</td></tr>' for k, v in rows)
    desc = f'<p style="margin:12px 0;color:#334155">{esc(p["description"])}</p>' if p["description"] else ""
    return (f'<div style="font-family:Arial,sans-serif;font-size:14px;color:#0f172a">'
            f'<p style="margin:0 0 4px"><span style="background:{color};color:#fff;border-radius:4px;padding:2px 8px;font-size:12px">'
            f'{esc(p["priority"])}</span> <b>{esc(p["title"])}</b></p>'
            f'<table style="border-collapse:collapse;margin-top:8px">{body}</table>{desc}'
            f'<p style="margin-top:16px"><a href="{esc(p["url"])}" style="background:#0f766e;color:#fff;padding:9px 16px;'
            f'border-radius:6px;text-decoration:none">{esc(_("Open the escalated query"))}</a></p></div>')


def _whatsapp_text(p: dict) -> str:
    return (f"🔔 {p['title']} [{p['priority']}]\n{p['name']} · {p['reference']}\n{_('Customer')}: {p['customer']}\n"
            f"{_('Type')}: {p['query_type']} · {p['escalation_type']}\n{_('Subject')}: {p['subject']}\n"
            f"{_('Assigned to')}: {p['assigned_to']}\n{p['url']}")


def notify(name: str, reason: str = "new"):
    """Send one escalation alert on every channel switched on. Each channel fails on its own."""
    if not frappe.db.exists(ESC, name):
        return
    doc = frappe.get_doc(ESC, name)
    s = settings()
    p = payload(doc, reason)
    users = recipients(doc, reason)
    sent = []
    subject = f"[{p['priority']}] {p['title']}: {p['subject']} ({doc.name})"
    if cint(s.notify_in_app):
        from thinknxg_support.integrations import alerts

        alerts.on_escalation(doc, reason, users, p)
        sent.append(_("in-app ({0})").format(len(users)))
    if cint(s.notify_system):
        n = 0
        for u in users:
            try:
                frappe.get_doc({"doctype": "Notification Log", "for_user": u, "type": "Alert", "subject": subject[:140],
                                "email_content": _email_html(p), "document_type": ESC, "document_name": doc.name,
                                "from_user": "Administrator"}).insert(ignore_permissions=True)
                n += 1
            except Exception:
                frappe.log_error(title="thinkNXG Support: escalation notification failed")
        sent.append(_("notification center ({0})").format(n))
    if cint(s.notify_email):
        emails = [frappe.db.get_value("User", u, "email") for u in users]
        emails += [e.strip() for e in (s.email_recipients or "").replace(",", "\n").splitlines() if e.strip()]
        emails = [e for e in dict.fromkeys(emails) if e and frappe.utils.validate_email_address(e)]
        if emails:
            try:
                frappe.sendmail(recipients=emails, subject=subject, message=_email_html(p), reference_doctype=ESC,
                                reference_name=doc.name, header=[p["title"], {"Critical": "red", "High": "orange"}.get(p["priority"], "blue")])
                sent.append(_("email ({0})").format(len(emails)))
            except Exception:
                frappe.log_error(title="thinkNXG Support: escalation email failed")
    if cint(s.notify_whatsapp):
        sent.append(_send_whatsapp(s, p))
    stamp = f"{frappe.utils.format_datetime(now_datetime())} · {_(REASON_TITLE.get(reason, reason))}: " + ", ".join(sent)
    frappe.db.set_value(ESC, doc.name, "notified", stamp[:1000], update_modified=False)


def _send_whatsapp(s, p: dict) -> str:
    numbers = ["".join(c for c in line if c.isdigit()) for line in (s.whatsapp_numbers or "").splitlines() if line.strip()]
    numbers = [n for n in numbers if 8 <= len(n) <= 15]
    if not numbers:
        return _("WhatsApp: no numbers")
    try:
        from thinknxg_support.integrations import whatsapp
    except Exception:
        return _("WhatsApp: not available")
    ok, failed = 0, 0
    for n in numbers:
        try:
            if s.whatsapp_template:
                params = [p["name"] + " · " + p["reference"], p["customer"], f"{p['query_type']} · {p['escalation_type']}",
                          p["subject"], p["priority"], p["url"]]
                whatsapp._send({"to": n, "type": "template", "template": {
                    "name": s.whatsapp_template, "language": {"code": s.whatsapp_template_language or "en"},
                    "components": [{"type": "body", "parameters": [{"type": "text", "text": str(x)[:1000]} for x in params]}]}})
            else:
                whatsapp._send({"to": n, "type": "text", "text": {"preview_url": False, "body": _whatsapp_text(p)[:4000]}})
            ok += 1
        except Exception as e:
            failed += 1
            frappe.log_error(title="thinkNXG Support: escalation WhatsApp alert failed", message=f"{n}: {e}")
    return _("WhatsApp ({0} sent, {1} failed)").format(ok, failed)


# ------------------------------------------------------------------ overdue job (every 5 minutes)
def check_overdue():
    if not enabled():
        return
    s = settings()
    now = now_datetime()
    rows = frappe.get_all(ESC, filters={"status": ["in", OPEN]},
                          fields=["name", "first_response_on", "response_due", "resolution_due", "response_overdue",
                                  "resolution_overdue"], limit=5000)
    for r in rows:
        resp = 1 if (not r.first_response_on and r.response_due and get_datetime(r.response_due) < now) else 0
        resol = 1 if (r.resolution_due and get_datetime(r.resolution_due) < now) else 0
        if (resp, resol) == (cint(r.response_overdue), cint(r.resolution_overdue)):
            continue
        frappe.db.set_value(ESC, r.name, {"response_overdue": resp, "resolution_overdue": resol,
                                          "overdue": 1 if (resp or resol) else 0}, update_modified=False)
        if cint(s.remind_overdue):
            if resp and not cint(r.response_overdue):
                _queue_notify(r.name, "overdue_response")
            elif resol and not cint(r.resolution_overdue):
                _queue_notify(r.name, "overdue_resolution")


# ------------------------------------------------------------------ customer interaction history
def interaction_history(doc) -> str:
    esc = frappe.utils.escape_html
    parts = []
    items = []
    if doc.reference_doctype == CONV and frappe.db.exists(CONV, doc.reference_name):
        for m in frappe.get_all("Support Portal Message", filters={"conversation": doc.reference_name},
                                fields=["direction", "sender_name", "sender_type", "content", "creation", "is_internal"],
                                order_by="creation desc", limit=40):
            who = m.sender_name or m.sender_type or ""
            tag = _("internal note") if m.is_internal else (_("customer") if m.direction == "Inbound" else (m.sender_type or _("agent")).lower())
            items.append((m.creation, who, tag, strip_html(m.content or "")[:400], m.direction == "Inbound"))
    elif doc.reference_doctype == "HD Ticket" and frappe.db.exists("DocType", "HD Ticket"):
        for c in frappe.get_all("Communication", filters={"reference_doctype": "HD Ticket", "reference_name": doc.reference_name,
                                                         "communication_type": "Communication"},
                                fields=["sent_or_received", "sender_full_name", "sender", "content", "creation"],
                                order_by="creation desc", limit=30):
            items.append((c.creation, c.sender_full_name or c.sender, _("customer") if c.sent_or_received == "Received" else _("agent"),
                          strip_html(c.content or "")[:400], c.sent_or_received == "Received"))
    elif doc.reference_doctype == "Support Request" and frappe.db.exists("Support Request", doc.reference_name):
        r = frappe.db.get_value("Support Request", doc.reference_name, ["details", "customer_response", "creation", "modified",
                                                                         "raised_by"], as_dict=True)
        if r.customer_response:
            items.append((r.modified, _("Support"), _("agent"), strip_html(r.customer_response)[:400], False))
        items.append((r.creation, r.raised_by, _("customer"), strip_html(r.details or "")[:400], True))
    if items:
        rows = "".join(
            f'<div style="padding:8px 10px;border-radius:8px;margin-bottom:6px;background:{"var(--subtle-fg)" if inbound else "var(--fg-color)"};'
            f'border:1px solid var(--border-color)"><div class="text-muted small">{esc(str(who or ""))} · {esc(tag)} · '
            f'{esc(frappe.utils.format_datetime(at))}</div><div>{esc(text)}</div></div>'
            for at, who, tag, text, inbound in items)
        parts.append(f'<h5 style="margin:4px 0 8px">{esc(_("Messages on this query"))} '
                     f'<small class="text-muted">({esc(_("newest first"))})</small></h5>{rows}')
    if doc.customer:
        others = frappe.get_all(ESC, filters={"customer": doc.customer, "name": ["!=", doc.name]},
                                fields=["name", "subject", "status", "query_type", "escalated_on"], order_by="escalated_on desc", limit=10)
        tickets = []
        if frappe.db.exists("DocType", "HD Ticket") and frappe.get_meta("HD Ticket").has_field("customer"):
            tickets = frappe.get_all("HD Ticket", filters={"customer": doc.customer}, fields=["name", "subject", "status", "creation"],
                                     order_by="creation desc", limit=10)
        requests_ = frappe.get_all("Support Request", filters={"customer": doc.customer},
                                   fields=["name", "subject", "status", "creation"], order_by="creation desc", limit=10)
        def table(title, rows, route):
            if not rows:
                return ""
            body = "".join(f'<tr><td><a href="/app/{route}/{esc(str(x.name))}">{esc(str(x.name))}</a></td><td>{esc(x.subject or "")}</td>'
                           f'<td>{esc(x.status or "")}</td><td class="text-muted">{esc(frappe.utils.format_date(x.get("escalated_on") or x.creation))}</td></tr>'
                           for x in rows)
            return f'<h5 style="margin:16px 0 6px">{esc(title)}</h5><table class="table table-sm table-bordered">{body}</table>'
        parts.append(table(_("Other escalations for this customer"), others, "support-escalation"))
        parts.append(table(_("Helpdesk tickets"), tickets, "hd-ticket"))
        parts.append(table(_("Service requests"), requests_, "support-request"))
    return "".join(parts) or f'<p class="text-muted">{esc(_("No earlier interaction found."))}</p>'
