"""Agent chat console API (desk page /app/support-chat). Staff roles only; DocType permissions apply."""
from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import cint, get_datetime, now_datetime, strip_html

from thinknxg_support.integrations import conversations, realtime, routing, whatsapp

CONV = "Support Conversation Link"
MSG = "Support Portal Message"
STAFF = ["Support Agent", "Support Manager", "Support Portal Administrator", "System Manager"]


def _doc(name, ptype="read"):
    frappe.only_for(STAFF)
    doc = frappe.get_doc(CONV, name)
    doc.check_permission(ptype)
    return doc


def _display_name(r) -> str:
    if r.get("channel") == "WhatsApp":
        return r.get("whatsapp_profile_name") or f"+{r.get('whatsapp_number')}"
    if r.get("is_guest"):
        return r.get("guest_name") or _("Visitor")
    return frappe.db.get_value("User", r.get("started_by"), "full_name") or r.get("customer") or r.get("subject")


@frappe.whitelist(methods=["GET"])
def inbox(status="active", channel=None, mine=0, search=None, queue=None):
    frappe.only_for(STAFF)
    filters = {}
    if status == "active":
        filters["status"] = ["!=", "Closed"]
    elif status == "waiting_agent":
        filters.update({"status": ["!=", "Closed"], "handling": "Queued"})
    elif status == "bot":
        filters.update({"status": ["!=", "Closed"], "handling": "Bot"})
    elif status in ("Open", "Waiting", "Closed"):
        filters["status"] = status
        if status == "Open":
            filters["handling"] = ["!=", "Bot"]
    if channel in ("Portal", "Live Chat", "WhatsApp"):
        filters["channel"] = channel
    if cint(mine):
        filters["assigned_agent"] = frappe.session.user
    if queue:
        filters["queue"] = queue
    or_filters = None
    if search:
        q = f"%{strip_html(search)[:60]}%"
        or_filters = [[CONV, f, "like", q] for f in ("subject", "guest_name", "guest_email", "whatsapp_number",
                                                     "whatsapp_profile_name", "customer", "name")]
    rows = frappe.get_list(CONV, filters=filters, or_filters=or_filters, limit=200, order_by="last_activity_at desc",
                           fields=["name", "subject", "status", "channel", "customer", "is_guest", "guest_name",
                                   "whatsapp_number", "whatsapp_profile_name", "started_by", "unread_agent",
                                   "assigned_agent", "last_activity_at", "last_message_reference",
                                   "whatsapp_window_expires", "helpdesk_ticket", "handling", "queue", "handoff_at"])
    previews = {}
    refs = [r.last_message_reference for r in rows if r.last_message_reference]
    if refs:
        for m in frappe.get_all(MSG, filters={"name": ["in", refs]}, fields=["name", "content", "direction", "sender_type"]):
            prefix = "" if m.direction == "Inbound" else ((m.sender_type or _("You")) + ": ")
            previews[m.name] = (prefix + strip_html(m.content or ""))[:90]
    for r in rows:
        r["display_name"] = _display_name(r)
        r["preview"] = previews.get(r.last_message_reference, "")
        r["window_open"] = bool(r.whatsapp_window_expires and get_datetime(r.whatsapp_window_expires) > now_datetime())
        r["customer_typing"] = bool(realtime.typing(r.name, "customer"))
        r.pop("last_message_reference", None)
    return rows


@frappe.whitelist(methods=["GET"])
def thread(name):
    doc = _doc(name)
    msgs = frappe.get_all(MSG, filters={"conversation": name}, order_by="creation asc", limit=1000,
                          fields=["name", "direction", "sender", "sender_name", "content", "attachment", "is_internal",
                                  "creation", "delivery_status", "delivery_error", "sender_type", "response_source",
                                  "confidence", "feedback", "actions_json", "read_by_customer", "read_by_agent"])
    unread = [m.name for m in msgs if m.direction == "Inbound" and not m.read_by_agent]
    if unread:
        frappe.db.sql("update `tabSupport Portal Message` set read_by_agent=1 where name in %s", (tuple(unread),))
        realtime.bump(name)
    if cint(doc.unread_agent):
        frappe.db.set_value(CONV, name, "unread_agent", 0, update_modified=False)
    for m in msgs:
        try:
            m["actions"] = json.loads(m.pop("actions_json") or "{}")
        except ValueError:
            m["actions"] = {}
    meta = {k: doc.get(k) for k in ("name", "subject", "status", "channel", "customer", "contact", "is_guest",
                                    "guest_name", "guest_email", "guest_phone", "source_page", "whatsapp_number",
                                    "whatsapp_profile_name", "whatsapp_window_expires", "assigned_agent",
                                    "helpdesk_ticket", "chat_rating", "guest_last_seen", "creation", "handling", "queue",
                                    "handoff_reason", "ai_replies")}
    meta["display_name"] = _display_name(doc.as_dict())
    meta["window_open"] = whatsapp.window_open(doc) if doc.channel == "WhatsApp" else None
    meta["customer_name"] = frappe.db.get_value("Customer", doc.customer, "customer_name") if doc.customer else None
    meta["assigned_name"] = frappe.db.get_value("User", doc.assigned_agent, "full_name") if doc.assigned_agent else None
    meta.update(_live_state(name))
    return {"conversation": meta, "messages": msgs}


@frappe.whitelist(methods=["GET"])
def live(name):
    """Cheap per-second state for the open conversation: typing, visitor presence, AI drafting."""
    _doc(name)
    return _live_state(name)


def _live_state(name):
    doc_seen = frappe.db.get_value(CONV, name, "guest_last_seen")
    return {
        "customer_typing": bool(realtime.typing(name, "customer")),
        "ai_drafting": bool(realtime.stream_state(name)),
        "visitor_online": bool(doc_seen and (now_datetime() - get_datetime(doc_seen)).total_seconds() < 60),
    }


@frappe.whitelist(methods=["POST"])
def reply(name, content, internal=0):
    doc = _doc(name, "write")
    if not strip_html(content or "").strip():
        frappe.throw(_("Write a message first."))
    return conversations.post_agent_message(doc, content, internal=cint(internal), source="desk")


@frappe.whitelist(methods=["POST"])
def typing(name):
    _doc(name)
    first = (frappe.db.get_value("User", frappe.session.user, "first_name") or "").strip()
    realtime.set_typing(name, "agent", first or "1")
    return {"ok": True}


@frappe.whitelist(methods=["POST"])
def heartbeat():
    frappe.only_for(STAFF)
    realtime.heartbeat(frappe.session.user)
    return {"ok": True}


@frappe.whitelist(methods=["POST"])
def take_over(name):
    doc = _doc(name, "write")
    routing.assign(doc, frappe.session.user, doc.queue, "Take Over")
    doc.db_set({"handling": "Agent"}, update_modified=False)
    if not doc.handoff_at:
        doc.db_set({"handoff_at": now_datetime(), "handoff_reason": _("Taken over by an agent")}, update_modified=False)
    first = (frappe.db.get_value("User", frappe.session.user, "first_name") or "").strip() or _("An agent")
    conversations.post_agent_message(doc, f"<p>{frappe.utils.escape_html(_('{0} joined the chat.').format(first))}</p>",
                                     sender="Administrator", source="system", sender_type="System",
                                     response_source="Agent joined")
    return {"ok": True}


@frappe.whitelist(methods=["POST"])
def return_to_assistant(name):
    doc = _doc(name, "write")
    from thinknxg_support.integrations.ai.engine import automation_applies

    if not automation_applies(doc):
        frappe.throw(_("No chatbot or AI assistant is enabled for this channel."))
    for row in frappe.get_all("Support Chat Assignment", filters={"conversation": name, "ended_at": ["is", "not set"]},
                              pluck="name"):
        frappe.db.set_value("Support Chat Assignment", row, {"ended_at": now_datetime(), "outcome": "Returned to Assistant"})
    doc.db_set({"handling": "Bot", "assigned_agent": None}, update_modified=False)
    conversations.post_agent_message(doc, "<p>" + frappe.utils.escape_html(
        _("You're back with our assistant. Ask for a person at any time.")) + "</p>",
        sender="Administrator", source="system", sender_type="System", response_source="Returned to assistant")
    return {"ok": True}


@frappe.whitelist(methods=["POST"])
def transfer(name, user=None, queue=None):
    doc = _doc(name, "write")
    if user and not frappe.db.exists("User", user):
        frappe.throw(_("User not found."))
    if queue and not frappe.db.exists("Support Chat Queue", queue):
        frappe.throw(_("Queue not found."))
    q = frappe.get_cached_doc("Support Chat Queue", queue) if queue else None
    agent = user or (routing.pick_agent(q) if q else None)
    routing.assign(doc, agent, queue or doc.queue, "Transfer")
    if doc.handling == "Bot":
        doc.db_set("handling", "Queued", update_modified=False)
    conversations.post_agent_message(doc, "<p>" + frappe.utils.escape_html(
        _("Transferred to {0}.").format(frappe.db.get_value("User", agent, "full_name") if agent else (queue or "")))
        + "</p>", sender=frappe.session.user, source="system", internal=1, sender_type="System")
    if agent and agent != frappe.session.user:
        frappe.get_doc({"doctype": "Notification Log", "for_user": agent, "type": "Alert",
                        "subject": _("Chat transferred to you: {0}").format(doc.subject),
                        "document_type": CONV, "document_name": name}).insert(ignore_permissions=True)
    return {"ok": True, "agent": agent}


@frappe.whitelist(methods=["POST"])
def assign(name, user=None):
    doc = _doc(name, "write")
    routing.assign(doc, user or frappe.session.user, doc.queue, "Manual")
    conversations.publish_agent_event(doc, "assigned")
    return {"ok": True}


@frappe.whitelist(methods=["POST"])
def set_status(name, status):
    doc = _doc(name, "write")
    if status not in ("Open", "Waiting", "Closed"):
        frappe.throw(_("Unknown status."))
    was = doc.status
    doc.db_set("status", status)
    if status == "Closed" and was != "Closed":
        routing.on_closed(doc)
    realtime.bump(name)
    conversations.publish_agent_event(doc, "status")
    return {"ok": True}


@frappe.whitelist(methods=["POST"])
def retry(message):
    frappe.only_for(STAFF)
    msg = frappe.get_doc(MSG, message)
    _doc(msg.conversation, "write")
    if msg.direction != "Outbound" or msg.delivery_status != "Failed":
        frappe.throw(_("Only failed WhatsApp messages can be retried."))
    msg.db_set({"delivery_status": "Pending", "delivery_error": None})
    frappe.enqueue(whatsapp.deliver, queue="short", enqueue_after_commit=True, message=msg.name)
    return {"ok": True}


@frappe.whitelist(methods=["GET"])
def queues():
    frappe.only_for(STAFF)
    return frappe.get_all("Support Chat Queue", filters={"enabled": 1}, pluck="name", order_by="priority desc")


@frappe.whitelist(methods=["GET"])
def summary():
    frappe.only_for(STAFF)
    rows = frappe.get_list(CONV, filters={"status": ["!=", "Closed"]}, fields=["channel", "unread_agent", "handling"],
                           limit=1000)
    out = {"unread": 0, "Portal": 0, "Live Chat": 0, "WhatsApp": 0, "waiting_agent": 0, "bot": 0}
    for r in rows:
        out[r.channel or "Portal"] = out.get(r.channel or "Portal", 0) + 1
        out["unread"] += cint(r.unread_agent)
        out["waiting_agent"] += 1 if r.handling == "Queued" else 0
        out["bot"] += 1 if r.handling == "Bot" else 0
    return out
