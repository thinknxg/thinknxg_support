"""Queues, agent assignment and handoff from the assistant to people."""
from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, now_datetime

from thinknxg_support.integrations import realtime

CONV = "Support Conversation Link"
CHANNEL_FIELD = {"Live Chat": "channel_live_chat", "WhatsApp": "channel_whatsapp", "Portal": "channel_portal"}


def pick_queue(channel: str):
    field = CHANNEL_FIELD.get(channel or "Portal")
    name = frappe.db.get_value("Support Chat Queue", {"enabled": 1, field: 1}, "name", order_by="priority desc, creation asc")
    return frappe.get_cached_doc("Support Chat Queue", name) if name else None


def open_load(user: str) -> int:
    return frappe.db.count(CONV, {"assigned_agent": user, "status": ["!=", "Closed"], "handling": ["in", ["Queued", "Agent"]]})


def pick_agent(queue) -> str | None:
    if not queue or queue.assignment_rule == "Manual":
        return None
    members = [m for m in queue.members if m.active and frappe.db.get_value("User", m.user, "enabled")]
    if queue.only_online_agents:
        members = [m for m in members if realtime.is_online(m.user)]
    members = [m for m in members if open_load(m.user) < (cint(m.max_chats) or 5)]
    if not members:
        return None
    if queue.assignment_rule == "Round Robin":
        key = f"thinknxg_support:rr:{queue.name}"
        last = frappe.cache.get_value(key)
        users = [m.user for m in members]
        nxt = users[(users.index(last) + 1) % len(users)] if last in users else users[0]
        frappe.cache.set_value(key, nxt)
        return nxt
    return min(members, key=lambda m: (open_load(m.user), m.idx)).user


def assign(conv, agent: str | None, queue: str | None, reason: str = "Automatic"):
    open_rows = frappe.get_all("Support Chat Assignment", filters={"conversation": conv.name, "ended_at": ["is", "not set"]},
                               pluck="name")
    for name in open_rows:
        frappe.db.set_value("Support Chat Assignment", name, {"ended_at": now_datetime(), "outcome": "Transferred"})
    if agent:
        frappe.get_doc({"doctype": "Support Chat Assignment", "conversation": conv.name, "agent": agent, "queue": queue,
                        "reason": reason, "assigned_at": now_datetime()}).insert(ignore_permissions=True)
    conv.db_set({"assigned_agent": agent, "queue": queue}, update_modified=False)


def handoff(conv, reason: str, message: str | None = None, announce: bool = True):
    """Move a conversation from the assistant to people. Safe to call twice."""
    from thinknxg_support.integrations import conversations, live_chat
    from thinknxg_support.integrations.notifications import notify_agents

    conv.reload()
    if conv.handling in ("Queued", "Agent") or conv.status == "Closed":
        return
    queue = pick_queue(conv.channel)
    agent = pick_agent(queue) if queue else None
    conv.db_set({"handling": "Queued", "handoff_at": now_datetime(), "handoff_reason": (reason or "")[:140]},
                update_modified=False)
    assign(conv, agent, queue.name if queue else None, "Automatic")
    if announce:
        if message:
            text = message
        elif not live_chat.is_online():
            text = live_chat.settings().chat_offline_message or _("Our team is offline now. We'll reply as soon as we're back.")
        elif agent:
            first = (frappe.db.get_value("User", agent, "first_name") or "").strip()
            text = _("Connecting you with {0} from our team.").format(first) if first else _("Connecting you with our team.")
        else:
            text = _("I've passed this to our team. Someone will reply here shortly.")
        conversations.post_agent_message(conv, f"<p>{frappe.utils.escape_html(text)}</p>", sender="Administrator",
                                         source="system", sender_type="System", response_source="Handoff")
    last = frappe.get_all("Support Portal Message", filters={"conversation": conv.name, "direction": "Inbound"},
                          order_by="creation desc", limit=1, pluck="name")
    msg = frappe.get_doc("Support Portal Message", last[0]) if last else None
    from thinknxg_support.integrations import raven

    if raven.available() and msg:
        raven.push_customer_message(conv, msg)
    elif msg:
        notify_agents(conv, msg)
    conversations.publish_agent_event(conv, "handoff")
    from thinknxg_support.audit import log_event

    log_event("Handoff", reference_doctype=CONV, reference_name=conv.name,
              details={"reason": reason, "queue": queue.name if queue else None, "agent": agent}, user="Administrator")


def agent_replied(conv, user: str):
    """Called when a person sends a customer-visible reply."""
    values = {"handling": "Agent"}
    if not conv.get("first_agent_reply_at"):
        values["first_agent_reply_at"] = now_datetime()
    if not conv.get("assigned_agent"):
        values["assigned_agent"] = user
        frappe.get_doc({"doctype": "Support Chat Assignment", "conversation": conv.name, "agent": user,
                        "queue": conv.get("queue"), "reason": "Take Over", "assigned_at": now_datetime(),
                        "first_response_at": now_datetime()}).insert(ignore_permissions=True)
    else:
        row = frappe.db.get_value("Support Chat Assignment", {"conversation": conv.name, "agent": conv.assigned_agent,
                                                              "ended_at": ["is", "not set"], "first_response_at": ["is", "not set"]})
        if row:
            frappe.db.set_value("Support Chat Assignment", row, "first_response_at", now_datetime())
    frappe.db.set_value(CONV, conv.name, values, update_modified=False)
    conv.update(values)


def on_closed(conv):
    bot_replies = frappe.db.count("Support Portal Message", {"conversation": conv.name, "sender_type": ["in", ["AI", "Bot"]]})
    values = {"resolved_at": now_datetime(),
              "resolved_by_assistant": 1 if (not conv.get("first_agent_reply_at") and bot_replies) else 0}
    frappe.db.set_value(CONV, conv.name, values, update_modified=False)
    for name in frappe.get_all("Support Chat Assignment", filters={"conversation": conv.name, "ended_at": ["is", "not set"]},
                               pluck="name"):
        frappe.db.set_value("Support Chat Assignment", name, {"ended_at": now_datetime(), "outcome": "Resolved"})
