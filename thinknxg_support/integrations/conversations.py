"""Provider-agnostic conversation service (portal-native store + optional Raven bridge)."""
from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import cint, now_datetime, strip_html

from thinknxg_support.integrations import helpdesk, raven
from thinknxg_support.security import PortalAccessError, PortalUser, log_denied
from thinknxg_support.utils import clean_html, clean_text

CONV = "Support Conversation Link"
MSG = "Support Portal Message"


def conversation_visible(pu: PortalUser, conv, customer: str) -> bool:
    if conv.customer != customer or customer not in pu.customers:
        return False
    if conv.started_by == pu.user:
        return True
    return conv.visibility == "Organization" and pu.can("conversations.organization", customer)


def assert_conversation(pu: PortalUser, name: str, customer: str):
    conv = frappe.get_doc(CONV, name) if name and frappe.db.exists(CONV, name) else None
    if conv and conversation_visible(pu, conv, customer):
        return conv
    log_denied(pu, CONV if conv else None, name, "conversation access denied")
    raise PortalAccessError(_("Conversation not found."))


def list_conversations(pu: PortalUser, customer: str) -> list[dict]:
    or_filters = [[CONV, "started_by", "=", pu.user]]
    if pu.can("conversations.organization", customer):
        or_filters.append([CONV, "visibility", "=", "Organization"])
    rows = frappe.get_all(
        CONV,
        filters={"customer": customer},
        or_filters=or_filters,
        fields=["name", "subject", "status", "conversation_type", "channel", "helpdesk_ticket", "last_activity_at",
                "unread_customer", "started_by", "creation"],
        order_by="last_activity_at desc",
        limit=200,
    )
    for r in rows:
        r["is_mine"] = r.started_by == pu.user
        r["unread"] = cint(r.pop("unread_customer")) if r["is_mine"] else 0
        r.pop("started_by", None)
    return rows


def unread_total(pu: PortalUser, customer: str) -> int:
    val = frappe.db.sql(
        "select coalesce(sum(unread_customer), 0) from `tabSupport Conversation Link` "
        "where customer=%s and started_by=%s",
        (customer, pu.user),
    )
    return cint(val[0][0]) if val else 0


def start(pu: PortalUser, customer: str, subject: str, message: str, conversation_type: str = "Customer Chat",
          visibility: str = "Participant", client_message_id: str | None = None, files=None,
          channel: str = "Portal") -> dict:
    if conversation_type not in ("Customer Chat", "Service Conversation", "Live Chat"):
        conversation_type = "Customer Chat"
    if visibility not in ("Participant", "Organization"):
        visibility = "Participant"
    if client_message_id:
        existing = frappe.db.get_value(MSG, {"client_message_id": client_message_id, "sender": pu.user}, "conversation")
        if existing:
            return {"name": existing, "duplicate": True}
    conv = frappe.get_doc({
        "doctype": CONV,
        "subject": clean_text(subject, 140) or _("Conversation"),
        "customer": customer,
        "contact": pu.contacts[0] if pu.contacts else None,
        "started_by": pu.user,
        "visibility": visibility,
        "conversation_type": conversation_type,
        "channel": channel if channel in ("Portal", "Live Chat") else "Portal",
        "status": "Open",
        "external_provider": "Portal Native",
        "last_activity_at": now_datetime(),
    })
    conv.insert(ignore_permissions=True)
    post_customer_message(pu, conv, message, client_message_id=client_message_id, files=files)
    return {"name": conv.name}


CUSTOMER_FIELDS = ["name", "direction", "sender", "sender_name", "content", "attachment", "creation", "sender_type",
                   "actions_json", "feedback", "read_by_agent"]


def customer_view(r, me: str | None = None) -> dict:
    """The only shape in which messages leave the server for customers and guests (internal notes never reach it)."""
    inbound = r.direction == "Inbound"
    st = r.get("sender_type") or ("Customer" if inbound else "Agent")
    try:
        actions = json.loads(r.get("actions_json") or "{}") or {}
    except ValueError:
        actions = {}
    if inbound:
        author = r.sender_name
    elif st in ("AI", "Bot"):
        author = r.sender_name or _("Assistant")
    elif st == "System":
        author = ""
    else:
        author = (r.sender_name or "").split(" ")[0] or _("Support")
    return {
        "id": r.name,
        "from_customer": inbound,
        "is_me": bool(me and r.sender == me and me != "Guest"),
        "author": author,
        "sender_type": st,
        "content": r.content,
        "has_attachment": bool(r.attachment),
        "attachment_name": (r.attachment or "").rsplit("/", 1)[-1] or None,
        "created": r.creation,
        "buttons": actions.get("buttons") or [],
        "follow_ups": actions.get("follow_ups") or [],
        "sources": actions.get("sources") or [],
        "feedback": r.get("feedback") or None,
        "can_feedback": st == "AI",
        "seen": bool(inbound and r.get("read_by_agent")),
    }


def messages(pu: PortalUser, conv) -> list[dict]:
    rows = frappe.get_all(MSG, filters={"conversation": conv.name, "is_internal": 0}, fields=CUSTOMER_FIELDS,
                          order_by="creation asc", limit=1000)
    out = [customer_view(r, pu.user) for r in rows]
    if conv.started_by == pu.user and cint(conv.unread_customer):
        frappe.db.set_value(CONV, conv.name, "unread_customer", 0, update_modified=False)
        frappe.db.sql(
            "update `tabSupport Portal Message` set read_by_customer=1 where conversation=%s and direction='Outbound'",
            (conv.name,),
        )
    return out


def post_customer_message(pu: PortalUser, conv, content: str, client_message_id: str | None = None,
                          files=None, button_payload: str | None = None) -> dict:
    return add_inbound_message(conv, content, sender=pu.user, sender_name=pu.full_name,
                               client_message_id=client_message_id, files=files, button_payload=button_payload)


def add_inbound_message(conv, content: str, *, sender: str | None, sender_name: str,
                        client_message_id: str | None = None, files=None, external_id: str | None = None,
                        attachment_url: str | None = None, allow_html: bool = True, reopen: bool = False,
                        button_payload: str | None = None) -> dict:
    """Single entry point for messages FROM the customer side: portal users, guests and WhatsApp."""
    if conv.status == "Closed" and not reopen:
        frappe.throw(_("This conversation is closed. Please start a new one."))
    if client_message_id:
        client_message_id = clean_text(client_message_id, 64)
        dup = frappe.db.get_value(MSG, {"conversation": conv.name, "client_message_id": client_message_id}, "name")
        if dup:
            return {"name": dup, "duplicate": True}
    if external_id:
        dup = frappe.db.get_value(MSG, {"external_message_id": external_id}, "name")
        if dup:
            return {"name": dup, "duplicate": True}
    content = clean_html(content) if allow_html else _text_to_html(content)
    if not strip_html(content).strip() and not files and not attachment_url:
        frappe.throw(_("Please write a message."))

    msg = frappe.get_doc({
        "doctype": MSG,
        "conversation": conv.name,
        "direction": "Inbound",
        "sender": sender if sender and sender != "Guest" else None,
        "sender_name": clean_text(sender_name, 140) or _("Visitor"),
        "content": content,
        "client_message_id": client_message_id,
        "external_message_id": external_id,
        "channel": conv.get("channel") or "Portal",
        "attachment": attachment_url,
        "sender_type": "Customer",
        "button_payload": clean_text(button_payload, 140) or None,
    })
    msg.insert(ignore_permissions=True)
    if files:
        from thinknxg_support.utils import save_private_file

        fname, data = files[0]
        saved = save_private_file(fname, data, MSG, msg.name)
        msg.db_set("attachment", frappe.db.get_value("File", saved["name"], "file_url"))

    frappe.db.sql(
        "update `tabSupport Conversation Link` set unread_agent = unread_agent + 1, last_activity_at=%s, "
        "status='Open', last_message_reference=%s where name=%s",
        (now_datetime(), msg.name, conv.name),
    )
    from thinknxg_support.integrations import realtime

    if not conv.get("handling"):
        from thinknxg_support.integrations.ai.engine import initial_handling

        conv.handling = initial_handling(conv)
        frappe.db.set_value(CONV, conv.name, "handling", conv.handling, update_modified=False)
    realtime.bump(conv.name)
    publish_agent_event(conv, "message")
    if conv.handling == "Bot":
        frappe.enqueue("thinknxg_support.integrations.ai.engine.respond", queue="default", enqueue_after_commit=True,
                       conversation=conv.name, message=msg.name)
        return {"name": msg.name}
    if raven.available():
        raven.push_customer_message(conv, msg)
    else:
        from thinknxg_support.integrations.notifications import notify_agents

        notify_agents(conv, msg)
    return {"name": msg.name}


def _text_to_html(text: str) -> str:
    text = frappe.utils.escape_html(str(text or "").strip())[:20000]
    return "".join(f"<p>{p.replace(chr(10), '<br>')}</p>" for p in text.split("\n\n") if p.strip())


def publish_agent_event(conv, kind: str):
    """Tell open agent consoles that something changed. Only users who can read the DocType get it."""
    frappe.publish_realtime(
        "thinknxg_support_chat",
        {"conversation": conv.name, "kind": kind, "channel": conv.get("channel")},
        doctype=CONV,
        after_commit=True,
    )


def post_agent_message(conv, content: str, internal: int = 0, source: str = "desk", sender: str | None = None,
                       external_id: str | None = None, sender_type: str = "Agent", response_source: str | None = None,
                       sender_name: str | None = None, actions: dict | None = None, confidence: str | None = None,
                       ai_usage: str | None = None) -> dict:
    """Every message TO the customer goes through here: agents, the assistant, chatbot rules and system notes."""
    sender = sender or frappe.session.user
    if external_id:
        dup = frappe.db.get_value(MSG, {"external_message_id": external_id}, "name")
        if dup:
            return {"name": dup, "duplicate": True}
    human = sender_type == "Agent"
    if human and conv.status == "Closed" and not cint(internal) and conv.get("channel") == "Live Chat" and conv.get("is_guest"):
        frappe.throw(_("The visitor has ended this chat. Reply by email instead."))
    msg = frappe.get_doc({
        "doctype": MSG,
        "conversation": conv.name,
        "direction": "Outbound",
        "sender": sender,
        "sender_name": sender_name or frappe.db.get_value("User", sender, "full_name") or sender,
        "content": clean_html(content),
        "is_internal": cint(internal),
        "external_message_id": external_id,
        "channel": conv.get("channel") or "Portal",
        "delivery_status": "Pending" if conv.get("channel") == "WhatsApp" and not cint(internal) else None,
        "sender_type": sender_type,
        "response_source": response_source or ("Human" if human else sender_type),
        "confidence": confidence,
        "actions_json": json.dumps(actions) if actions else None,
        "ai_usage": ai_usage,
    })
    msg.insert(ignore_permissions=True)
    if not cint(internal):
        frappe.db.sql(
            "update `tabSupport Conversation Link` set unread_customer = unread_customer + 1, "
            "last_activity_at=%s, status='Waiting', last_message_reference=%s where name=%s",
            (now_datetime(), msg.name, conv.name),
        )
        if human:
            from thinknxg_support.integrations import routing

            routing.agent_replied(conv, sender)
        if conv.get("channel") == "WhatsApp":
            from thinknxg_support.integrations import whatsapp

            frappe.enqueue(whatsapp.deliver, queue="short", enqueue_after_commit=True, message=msg.name)
        elif human:
            from thinknxg_support.integrations.notifications import notify_customer_message

            notify_customer_message(conv, msg)
        if source == "desk":
            raven.mirror_agent_message(conv, msg)
    from thinknxg_support.integrations import realtime

    realtime.bump(conv.name)
    publish_agent_event(conv, "reply")
    return {"name": msg.name}


def escalate_to_ticket(conv, actor: str = "customer", pu: PortalUser | None = None) -> str:
    helpdesk.require()
    if conv.helpdesk_ticket:
        return conv.helpdesk_ticket
    rows = frappe.get_all(MSG, filters={"conversation": conv.name, "is_internal": 0},
                          fields=["direction", "sender_name", "content", "creation"], order_by="creation asc", limit=200)
    transcript = "".join(
        f"<p><b>{frappe.utils.escape_html(r.sender_name or '')}</b> "
        f"<small>{frappe.utils.format_datetime(r.creation)}</small></p>{r.content or ''}<hr>"
        for r in rows
    )
    if conv.get("is_guest"):
        raised_by = conv.guest_email
        if not raised_by:
            frappe.throw(_("Add the visitor's email or link the chat to a customer before creating a ticket."))
    elif not conv.started_by and conv.contact:
        raised_by = frappe.db.get_value("Contact", conv.contact, "email_id")
        if not raised_by:
            frappe.throw(_("The linked contact has no email address. Add one before creating a ticket."))
    else:
        raised_by = frappe.db.get_value("User", conv.started_by, "email") or conv.started_by
    ticket = helpdesk.create_ticket(
        subject=conv.subject,
        description=f"<p>{_('Escalated from portal conversation')} {conv.name}</p>{transcript}",
        raised_by=raised_by,
        customer=conv.customer,
        contact=conv.contact,
        via="escalation",
    )
    conv.db_set({"helpdesk_ticket": ticket, "conversation_type": "Ticket Discussion"})
    post_agent_message(conv, _("This conversation is now tracked as ticket #{0}.").format(ticket),
                       sender="Administrator", source="system", sender_type="System", response_source="Escalation")
    from thinknxg_support.audit import log_event

    log_event("Escalation", reference_doctype=CONV, reference_name=conv.name,
              details={"ticket": ticket, "actor": actor}, user=pu.user if pu else None)
    return ticket
