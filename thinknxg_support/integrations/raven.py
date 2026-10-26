"""Raven bridge.

Customers never join Raven channels. Each bridged conversation gets a PRIVATE
Raven channel whose members are agents only. Customer messages are posted by the
configured Raven Bot; agent messages are relayed back to the customer only when
they satisfy the relay rule (default: start with the reply prefix). Every hop is
recorded in Support Message Mapping (unique dedupe_key) so retries never create
duplicates and bridge-originated messages are never re-imported (loop prevention).
"""
from __future__ import annotations

import re

import frappe
from frappe.utils import cint, strip_html

from thinknxg_support.integrations import capabilities
from thinknxg_support.utils import settings

BRIDGE_FLAG = "thinknxg_support_bridging"
STAFF_ROLES = {"Support Agent", "Support Manager", "Support Portal Administrator", "System Manager"}


def available() -> bool:
    s = settings()
    rv = capabilities.get().get("raven", {})
    if not (s.enable_raven and rv.get("ok") and s.raven_bot):
        return False
    if rv.get("bot_doctype") and not frappe.db.exists("Raven Bot", s.raven_bot):
        return False
    return True


def _mapping_exists(key: str) -> bool:
    return bool(frappe.db.exists("Support Message Mapping", {"dedupe_key": key}))


def _record(key, conv, direction, portal_message=None, external_id=None, state="Delivered", error=None):
    name = frappe.db.get_value("Support Message Mapping", {"dedupe_key": key})
    if name:
        doc = frappe.get_doc("Support Message Mapping", name)
        doc.attempts = cint(doc.attempts) + 1
    else:
        doc = frappe.new_doc("Support Message Mapping")
        doc.dedupe_key = key
        doc.attempts = 1
    doc.update({
        "conversation": conv, "provider": "Raven", "direction": direction,
        "portal_message": portal_message, "external_message_id": external_id,
        "delivery_state": state, "last_error": (error or "")[:1000] or None,
    })
    doc.flags.ignore_permissions = True
    doc.save()
    return doc


# ------------------------------------------------------------------ channel
def ensure_channel(conv) -> str | None:
    if not available():
        return None
    if conv.external_provider == "Raven" and conv.external_conversation_id and frappe.db.exists(
        "Raven Channel", conv.external_conversation_id
    ):
        return conv.external_conversation_id
    s = settings()
    cf = capabilities.get()["raven"].get("channel_fields", {})
    slug = re.sub(r"[^a-z0-9-]", "-", f"support-{conv.name}".lower())[:60]
    values = {"doctype": "Raven Channel", "channel_name": slug, "type": "Private"}
    if cf.get("channel_description"):
        values["channel_description"] = f"Customer support: {conv.subject}"[:140]
    if cf.get("workspace") and s.raven_workspace:
        values["workspace"] = s.raven_workspace
    frappe.flags[BRIDGE_FLAG] = True
    try:
        channel = frappe.get_doc(values)
        channel.insert(ignore_permissions=True)
        members = [m.strip() for m in (s.raven_default_members or "").splitlines() if m.strip()]
        if conv.assigned_agent:
            members.append(conv.assigned_agent)
        for user in dict.fromkeys(members):
            if frappe.db.exists("User", user) and not frappe.db.exists(
                "Raven Channel Member", {"channel_id": channel.name, "user_id": user}
            ):
                frappe.get_doc({"doctype": "Raven Channel Member", "channel_id": channel.name,
                                "user_id": user}).insert(ignore_permissions=True)
    finally:
        frappe.flags[BRIDGE_FLAG] = False
    conv.db_set({"external_provider": "Raven", "external_conversation_id": channel.name})
    return channel.name


# ------------------------------------------------------------------ outbound (portal -> raven)
def push_customer_message(conv, portal_msg) -> None:
    """Post a customer message into the agents' Raven channel via the bot."""
    key = f"raven-out:{portal_msg.name}"
    existing = frappe.db.get_value("Support Message Mapping", {"dedupe_key": key}, "delivery_state")
    if existing == "Delivered":
        return
    try:
        channel = ensure_channel(conv)
        if not channel:
            return
        s = settings()
        if conv.get("channel") == "WhatsApp":
            who = f"WhatsApp +{conv.whatsapp_number}" + (f", {conv.customer}" if conv.customer else "")
        else:
            who = conv.customer or (f"guest, {conv.guest_email}" if conv.get("is_guest") else "")
        text = (f"<p><b>{frappe.utils.escape_html(portal_msg.sender_name or 'Customer')}</b> "
                f"({frappe.utils.escape_html(who)}):</p>{portal_msg.content or ''}"
                f"<p><i>Reply with {frappe.utils.escape_html(s.raven_reply_prefix or '')} "
                f"to answer the customer. Other messages stay internal.</i></p>")
        values = {"doctype": "Raven Message", "channel_id": channel, "text": text, "message_type": "Text"}
        mf = capabilities.get()["raven"].get("message_fields", {})
        if mf.get("is_bot_message"):
            values["is_bot_message"] = 1
        if mf.get("bot"):
            values["bot"] = s.raven_bot
        frappe.flags[BRIDGE_FLAG] = True
        try:
            msg = frappe.get_doc(values)
            msg.insert(ignore_permissions=True)
        finally:
            frappe.flags[BRIDGE_FLAG] = False
        _record(key, conv.name, "Outbound", portal_msg.name, msg.name, "Delivered")
        _record(f"raven-in:{msg.name}", conv.name, "Inbound", portal_msg.name, msg.name, "Skipped")
    except Exception as e:
        frappe.log_error(title="thinkNXG Support: Raven delivery failed")
        _record(key, conv.name, "Outbound", portal_msg.name, None, "Failed", str(e))
        from thinknxg_support.audit import log_event

        log_event("Integration Error", severity="Error", reference_doctype="Support Conversation Link",
                  reference_name=conv.name, details="raven outbound delivery failed")


def mirror_agent_message(conv, portal_msg) -> None:
    """Agent replied from desk: mirror into the Raven channel so the team sees it."""
    if conv.external_provider != "Raven" or not available():
        return
    key = f"raven-mirror:{portal_msg.name}"
    if _mapping_exists(key):
        return
    values = {"doctype": "Raven Message", "channel_id": conv.external_conversation_id,
              "text": f"<p><i>Sent to customer by {frappe.utils.escape_html(portal_msg.sender_name or '')}:</i></p>"
                      f"{portal_msg.content or ''}", "message_type": "Text"}
    mf = capabilities.get()["raven"].get("message_fields", {})
    if mf.get("is_bot_message"):
        values["is_bot_message"] = 1
    if mf.get("bot"):
        values["bot"] = settings().raven_bot
    frappe.flags[BRIDGE_FLAG] = True
    try:
        msg = frappe.get_doc(values).insert(ignore_permissions=True)
        _record(key, conv.name, "Outbound", portal_msg.name, msg.name, "Delivered")
        _record(f"raven-in:{msg.name}", conv.name, "Inbound", portal_msg.name, msg.name, "Skipped")
    except Exception as e:
        _record(key, conv.name, "Outbound", portal_msg.name, None, "Failed", str(e))
    finally:
        frappe.flags[BRIDGE_FLAG] = False


# ------------------------------------------------------------------ inbound (raven -> portal)
def on_raven_message(doc, method=None):
    if frappe.flags.get(BRIDGE_FLAG):
        return
    if cint(doc.get("is_bot_message")):
        return
    if not available():
        return
    conv_name = frappe.db.get_value(
        "Support Conversation Link",
        {"external_provider": "Raven", "external_conversation_id": doc.get("channel_id")},
    )
    if not conv_name:
        return
    key = f"raven-in:{doc.name}"
    if _mapping_exists(key):
        return
    if not (set(frappe.get_roles(doc.owner)) & STAFF_ROLES):
        _record(key, conv_name, "Inbound", None, doc.name, "Skipped", "sender is not support staff")
        return
    if doc.get("message_type") not in (None, "", "Text"):
        _record(key, conv_name, "Inbound", None, doc.name, "Skipped", "non-text messages are not relayed")
        return

    s = settings()
    html = doc.get("text") or ""
    plain = strip_html(html).strip()
    if s.raven_relay_mode == "Prefix Required":
        prefix = (s.raven_reply_prefix or "").strip()
        if not prefix or not plain.startswith(prefix):
            _record(key, conv_name, "Inbound", None, doc.name, "Skipped", "internal (no reply prefix)")
            return
        html = _strip_prefix(html, prefix)

    from thinknxg_support.integrations.conversations import post_agent_message

    conv = frappe.get_doc("Support Conversation Link", conv_name)
    msg = post_agent_message(conv, html, internal=0, source="raven", sender=doc.owner, external_id=doc.name)
    _record(key, conv_name, "Inbound", msg.get("name"), doc.name, "Delivered")


def _strip_prefix(html: str, prefix: str) -> str:
    idx = html.find(prefix)
    return html[:idx] + html[idx + len(prefix):] if idx >= 0 else html


def retry_failed():
    if not available():
        return
    rows = frappe.get_all(
        "Support Message Mapping",
        filters={"provider": "Raven", "direction": "Outbound", "delivery_state": "Failed", "attempts": ["<", 5],
                 "dedupe_key": ["like", "raven-out:%"]},
        fields=["name", "conversation", "portal_message"],
        limit=200,
    )
    for r in rows:
        if not (r.conversation and r.portal_message):
            continue
        conv = frappe.get_doc("Support Conversation Link", r.conversation)
        msg = frappe.get_doc("Support Portal Message", r.portal_message)
        push_customer_message(conv, msg)
        frappe.db.commit()
