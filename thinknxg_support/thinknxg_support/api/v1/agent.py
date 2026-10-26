"""Agent chat console API (desk page /app/support-chat). Staff roles only; DocType permissions apply."""
from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, get_datetime, now_datetime, strip_html

from thinknxg_support.integrations import conversations, whatsapp

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
def inbox(status="active", channel=None, mine=0, search=None):
    frappe.only_for(STAFF)
    filters = {}
    if status == "active":
        filters["status"] = ["!=", "Closed"]
    elif status in ("Open", "Waiting", "Closed"):
        filters["status"] = status
    if channel in ("Portal", "Live Chat", "WhatsApp"):
        filters["channel"] = channel
    if cint(mine):
        filters["assigned_agent"] = frappe.session.user
    or_filters = None
    if search:
        q = f"%{strip_html(search)[:60]}%"
        or_filters = [[CONV, f, "like", q] for f in ("subject", "guest_name", "guest_email", "whatsapp_number",
                                                     "whatsapp_profile_name", "customer", "name")]
    rows = frappe.get_list(CONV, filters=filters, or_filters=or_filters, limit=200, order_by="last_activity_at desc",
                           fields=["name", "subject", "status", "channel", "customer", "is_guest", "guest_name",
                                   "whatsapp_number", "whatsapp_profile_name", "started_by", "unread_agent",
                                   "assigned_agent", "last_activity_at", "last_message_reference",
                                   "whatsapp_window_expires", "helpdesk_ticket"])
    previews = {}
    refs = [r.last_message_reference for r in rows if r.last_message_reference]
    if refs:
        for m in frappe.get_all(MSG, filters={"name": ["in", refs]}, fields=["name", "content", "direction"]):
            previews[m.name] = (("" if m.direction == "Inbound" else _("You") + ": ") + strip_html(m.content or ""))[:90]
    for r in rows:
        r["display_name"] = _display_name(r)
        r["preview"] = previews.get(r.last_message_reference, "")
        r["window_open"] = bool(r.whatsapp_window_expires and get_datetime(r.whatsapp_window_expires) > now_datetime())
        r.pop("last_message_reference", None)
    return rows


@frappe.whitelist(methods=["GET"])
def thread(name):
    doc = _doc(name)
    msgs = frappe.get_all(MSG, filters={"conversation": name}, order_by="creation asc", limit=1000,
                          fields=["name", "direction", "sender", "sender_name", "content", "attachment", "is_internal",
                                  "creation", "delivery_status", "delivery_error"])
    if cint(doc.unread_agent):
        frappe.db.set_value(CONV, name, "unread_agent", 0, update_modified=False)
    meta = {k: doc.get(k) for k in ("name", "subject", "status", "channel", "customer", "contact", "is_guest",
                                    "guest_name", "guest_email", "guest_phone", "source_page", "whatsapp_number",
                                    "whatsapp_profile_name", "whatsapp_window_expires", "assigned_agent",
                                    "helpdesk_ticket", "chat_rating", "guest_last_seen", "creation")}
    meta["display_name"] = _display_name(doc.as_dict())
    meta["window_open"] = whatsapp.window_open(doc) if doc.channel == "WhatsApp" else None
    meta["customer_name"] = frappe.db.get_value("Customer", doc.customer, "customer_name") if doc.customer else None
    meta["visitor_online"] = bool(doc.guest_last_seen
                                  and (now_datetime() - get_datetime(doc.guest_last_seen)).total_seconds() < 60)
    return {"conversation": meta, "messages": msgs}


@frappe.whitelist(methods=["POST"])
def reply(name, content, internal=0):
    doc = _doc(name, "write")
    if not strip_html(content or "").strip():
        frappe.throw(_("Write a message first."))
    if not doc.assigned_agent and not cint(internal):
        doc.db_set("assigned_agent", frappe.session.user, update_modified=False)
    return conversations.post_agent_message(doc, content, internal=cint(internal), source="desk")


@frappe.whitelist(methods=["POST"])
def assign(name, user=None):
    doc = _doc(name, "write")
    doc.db_set("assigned_agent", user or frappe.session.user)
    conversations.publish_agent_event(doc, "assigned")
    return {"ok": True}


@frappe.whitelist(methods=["POST"])
def set_status(name, status):
    doc = _doc(name, "write")
    if status not in ("Open", "Waiting", "Closed"):
        frappe.throw(_("Unknown status."))
    doc.db_set("status", status)
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
def summary():
    frappe.only_for(STAFF)
    rows = frappe.get_list(CONV, filters={"status": ["!=", "Closed"]}, fields=["channel", "unread_agent"], limit=1000)
    out = {"unread": 0, "Portal": 0, "Live Chat": 0, "WhatsApp": 0}
    for r in rows:
        out[r.channel or "Portal"] = out.get(r.channel or "Portal", 0) + 1
        out["unread"] += cint(r.unread_agent)
    return out
