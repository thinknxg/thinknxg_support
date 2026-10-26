"""Live chat for logged-in customers and anonymous guests.

Guests authenticate each request with a random token returned when the chat starts.
Only its SHA-256 hash is stored, so a database leak does not expose live sessions.
Guest identity is never trusted to link a chat to a Customer: an agent does that
explicitly after verifying who the visitor is.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from urllib.parse import quote

import frappe
from frappe import _
from frappe.utils import add_to_date, cint, get_datetime, get_time, now_datetime, strip_html, validate_email_address

from thinknxg_support import ratelimit
from thinknxg_support.audit import log_event
from thinknxg_support.integrations import conversations
from thinknxg_support.security import PortalAccessError, get_portal_user
from thinknxg_support.utils import clean_text, settings

CONV = "Support Conversation Link"
MSG = "Support Portal Message"
DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


# ------------------------------------------------------------------ configuration
def is_online(at=None) -> bool:
    s = settings()
    at = get_datetime(at or now_datetime())
    days = {d.strip()[:3].title() for d in (s.chat_days or "").split(",") if d.strip()}
    if days and DAYS[at.weekday()] not in days:
        return False
    start = get_time(s.chat_start_time or "00:00:00")
    end = get_time(s.chat_end_time or "23:59:59")
    return start <= at.time() <= end


def whatsapp_url() -> str | None:
    s = settings()
    if not (s.show_whatsapp_button and s.whatsapp_display_number):
        return None
    digits = "".join(ch for ch in s.whatsapp_display_number if ch.isdigit())
    if len(digits) < 8:
        return None
    text = quote((s.whatsapp_prefill_text or "").strip())
    return f"https://wa.me/{digits}" + (f"?text={text}" if text else "")


def chat_mode() -> tuple[str, object]:
    """customer | guest | login | staff | off"""
    s = settings()
    if not s.enable_live_chat:
        return "off", None
    user = frappe.session.user
    if user == "Guest":
        return ("guest" if s.allow_guest_chat else "login"), None
    try:
        pu = get_portal_user(allow_staff_without_grant=True)
    except PortalAccessError:
        pu = None
    if pu and pu.grants:
        return "customer", pu
    if pu and pu.is_staff:
        return "staff", pu
    # logged in but not linked to an organisation: chat as a verified-identity guest
    return ("guest" if s.allow_guest_chat else "off"), None


def widget_config(context: str = "website") -> dict:
    s = settings()
    mode, _pu = chat_mode()
    user = frappe.session.user
    prefill = {}
    if user != "Guest":
        u = frappe.db.get_value("User", user, ["full_name", "email"], as_dict=True) or {}
        prefill = {"name": u.get("full_name"), "email": u.get("email"), "locked": True}
    lang = (frappe.db.get_value("Support Portal Profile", user, "language") if user != "Guest" else None) \
        or s.default_language or "en"
    return {
        "enabled": mode not in ("off", "staff") or bool(whatsapp_url() and mode != "staff"),
        "mode": mode,
        "show_on_website": bool(s.show_chat_on_website),
        "title": s.chat_title or _("Chat with support"),
        "greeting": s.chat_greeting,
        "offline_message": s.chat_offline_message,
        "privacy_note": s.chat_privacy_note,
        "online": is_online(),
        "position": (s.chat_position or "Right").lower(),
        "whatsapp_url": whatsapp_url(),
        "prefill": prefill,
        "lang": lang if lang in ("en", "ar") else "en",
        "brand": {"title": s.portal_title or "thinkNXG Support",
                  "logo": s.logo or "/assets/thinknxg_support/images/logo.svg",
                  "color": s.primary_color if str(s.primary_color or "").startswith("#") else "#0F766E"},
        "max_length": 4000,
    }


# ------------------------------------------------------------------ guest sessions
def _hash(token: str) -> str:
    return hashlib.sha256((token or "").encode()).hexdigest()


def _guest_conv(conversation: str, token: str):
    """Return the conversation if the token matches; identical error otherwise (no existence leak)."""
    conv = None
    if conversation and token and frappe.db.exists(CONV, conversation):
        conv = frappe.get_doc(CONV, conversation)
        if not (conv.is_guest and conv.guest_token_hash and hmac.compare_digest(conv.guest_token_hash, _hash(token))):
            conv = None
    if not conv:
        log_event("Access Denied", severity="Warning", reference_doctype=None, reference_name=None,
                  details="guest chat token rejected")
        raise frappe.PermissionError(_("This chat has ended or the link has expired. Please start a new chat."))
    return conv


def _clean_page(page: str | None) -> str | None:
    page = clean_text(page, 300)
    if not page:
        return None
    if page.startswith("/"):
        return page
    try:
        from urllib.parse import urlparse

        host = urlparse(frappe.utils.get_url()).netloc
        parsed = urlparse(page)
        return page if parsed.netloc == host else None
    except Exception:
        return None


def start_guest(message: str, name: str | None = None, email: str | None = None, phone: str | None = None,
                page: str | None = None, client_message_id: str | None = None) -> dict:
    s = settings()
    mode, _pu = chat_mode()
    if mode != "guest":
        frappe.throw(_("Chat is not available. Please log in to contact support."), frappe.PermissionError)
    ratelimit.check("guest_chat_start", 5, 3600)
    ratelimit.check("guest_chat_msg", s.guest_chat_rate_limit or 20, 600)

    user = frappe.session.user
    if user != "Guest":  # logged-in, unlinked user: identity comes from the account, not the form
        u = frappe.db.get_value("User", user, ["full_name", "email"], as_dict=True)
        name, email = u.full_name, u.email
    name = clean_text(name, 80)
    if len(name) < 2:
        frappe.throw(_("Please enter your name."))
    email = (email or "").strip().lower()
    if not validate_email_address(email):
        frappe.throw(_("Please enter a valid email address so we can reply."))
    phone_digits = "".join(ch for ch in (phone or "") if ch.isdigit() or ch == "+")[:20] or None
    if not strip_html(message or "").strip():
        frappe.throw(_("Please write a message."))
    if len(message or "") > 4000:
        frappe.throw(_("Message is too long."))

    token = secrets.token_urlsafe(32)
    conv = frappe.get_doc({
        "doctype": CONV,
        "subject": _("Live chat: {0}").format(name),
        "conversation_type": "Live Chat",
        "channel": "Live Chat",
        "status": "Open",
        "external_provider": "Portal Native",
        "is_guest": 1,
        "guest_name": name,
        "guest_email": email,
        "guest_phone": phone_digits,
        "source_page": _clean_page(page),
        "guest_ip": getattr(frappe.local, "request_ip", None),
        "guest_last_seen": now_datetime(),
        "guest_token_hash": _hash(token),
        "started_by": user if user != "Guest" else None,
        "last_activity_at": now_datetime(),
    })
    conv.insert(ignore_permissions=True)
    conversations.add_inbound_message(conv, message, sender=user, sender_name=name,
                                      client_message_id=client_message_id, allow_html=False)
    log_event("Guest Chat", reference_doctype=CONV, reference_name=conv.name, details="guest chat started")
    return {"conversation": conv.name, "token": token}


def guest_messages(conversation: str, token: str) -> dict:
    conv = _guest_conv(conversation, token)
    rows = frappe.get_all(MSG, filters={"conversation": conv.name, "is_internal": 0},
                          fields=["name", "direction", "sender_name", "content", "attachment", "creation"],
                          order_by="creation asc", limit=500)
    updates = {"unread_customer": 0}
    if not conv.guest_last_seen or get_datetime(conv.guest_last_seen) < add_to_date(now_datetime(), seconds=-20):
        updates["guest_last_seen"] = now_datetime()
    if cint(conv.unread_customer) or "guest_last_seen" in updates:
        frappe.db.set_value(CONV, conv.name, updates, update_modified=False)
    return {"conversation": conv.name, "status": conv.status, "rated": bool(conv.chat_rating),
            "messages": [_shape(r) for r in rows]}


def _shape(r) -> dict:
    inbound = r.direction == "Inbound"
    return {
        "id": r.name,
        "from_customer": inbound,
        "author": r.sender_name if inbound else ((r.sender_name or "").split(" ")[0] or _("Support")),
        "content": r.content,
        "has_attachment": bool(r.attachment),
        "created": r.creation,
    }


def guest_send(conversation: str, token: str, message: str, client_message_id: str | None = None) -> dict:
    conv = _guest_conv(conversation, token)
    ratelimit.check("guest_chat_msg", settings().guest_chat_rate_limit or 20, 600)
    if len(message or "") > 4000:
        frappe.throw(_("Message is too long."))
    frappe.db.set_value(CONV, conv.name, "guest_last_seen", now_datetime(), update_modified=False)
    return conversations.add_inbound_message(conv, message, sender=frappe.session.user, sender_name=conv.guest_name,
                                             client_message_id=client_message_id, allow_html=False)


def guest_end(conversation: str, token: str, rating=None) -> dict:
    conv = _guest_conv(conversation, token)
    _close(conv, rating)
    return {"ok": True}


def _close(conv, rating=None):
    values = {"status": "Closed"}
    if rating and not conv.chat_rating:
        values["chat_rating"] = max(1, min(5, cint(rating))) / 5.0
    conv.db_set(values)
    conversations.publish_agent_event(conv, "closed")


# ------------------------------------------------------------------ logged-in customers
def _active_customer_chat(pu, customer):
    name = frappe.db.get_value(
        CONV, {"customer": customer, "started_by": pu.user, "channel": "Live Chat", "status": ["!=", "Closed"]},
        "name", order_by="creation desc")
    return frappe.get_doc(CONV, name) if name else None


def customer_chat(pu, customer) -> dict:
    conv = _active_customer_chat(pu, customer)
    if not conv:
        return {"conversation": None, "status": None, "messages": []}
    return {"conversation": conv.name, "status": conv.status, "messages": conversations.messages(pu, conv)}


def customer_send(pu, customer, message: str, client_message_id=None, files=None) -> dict:
    ratelimit.check("message", settings().message_rate_limit)
    conv = _active_customer_chat(pu, customer)
    if not conv:
        return conversations.start(pu, customer, _("Live chat"), message, conversation_type="Live Chat",
                                   client_message_id=client_message_id, files=files, channel="Live Chat")
    return conversations.post_customer_message(pu, conv, message, client_message_id, files=files)


def customer_end(pu, customer, rating=None) -> dict:
    conv = _active_customer_chat(pu, customer)
    if not conv and rating:
        # rating submitted after the chat was ended: rate the customer's most recent live chat (last hour)
        name = frappe.db.get_value(
            CONV, {"customer": customer, "started_by": pu.user, "channel": "Live Chat", "status": "Closed",
                   "modified": [">", add_to_date(now_datetime(), hours=-1)]}, "name", order_by="modified desc")
        conv = frappe.get_doc(CONV, name) if name else None
    if conv:
        _close(conv, rating)
    return {"ok": True}


# ------------------------------------------------------------------ notifications & housekeeping
def email_guest_if_away(conv, msg):
    """Email an agent reply to a guest who is no longer looking at the chat window."""
    if not conv.guest_email:
        return
    if conv.guest_last_seen and get_datetime(conv.guest_last_seen) > add_to_date(now_datetime(), minutes=-2):
        return
    key = f"thinknxg_support:guest_mail:{conv.name}"
    if frappe.cache.get_value(key):
        return
    frappe.cache.set_value(key, 1, expires_in_sec=600)
    s = settings()
    body = (f"<p>{_('Hello {0},').format(frappe.utils.escape_html(conv.guest_name or ''))}</p>"
            f"<p>{_('Our support team replied to your chat:')}</p>"
            f"<blockquote>{msg.content or ''}</blockquote>"
            f"<p>{_('Reply to this email or open the chat on our website to continue.')}</p>")
    frappe.sendmail(
        recipients=[conv.guest_email],
        subject=_("Reply from {0}").format(s.portal_title or "thinkNXG Support"),
        message=body,
        reply_to=s.support_email or None,
        reference_doctype=CONV,
        reference_name=conv.name,
        delayed=True,
    )


def close_idle_chats():
    hours = cint(settings().chat_auto_close_hours) or 24
    cutoff = add_to_date(now_datetime(), hours=-hours)
    for name in frappe.get_all(CONV, filters={"channel": ["in", ["Live Chat", "WhatsApp"]], "status": ["!=", "Closed"],
                                              "last_activity_at": ["<", cutoff]}, pluck="name", limit=500):
        frappe.db.set_value(CONV, name, "status", "Closed", update_modified=False)


def purge_guest_chats():
    days = cint(settings().guest_chat_retention_days)
    if days <= 0:
        return
    cutoff = add_to_date(now_datetime(), days=-days)
    names = frappe.get_all(CONV, filters={"is_guest": 1, "status": "Closed", "last_activity_at": ["<", cutoff],
                                          "customer": ["is", "not set"]}, pluck="name", limit=500)
    for name in names:
        msgs = frappe.get_all(MSG, filters={"conversation": name}, pluck="name")
        for f in frappe.get_all("File", filters={"attached_to_doctype": MSG, "attached_to_name": ["in", msgs or [""]]},
                                pluck="name"):
            frappe.delete_doc("File", f, ignore_permissions=True, force=True)
        frappe.db.delete("Support Message Mapping", {"conversation": name})
        frappe.db.delete(MSG, {"conversation": name})
        frappe.delete_doc(CONV, name, ignore_permissions=True, force=True)
    if names:
        log_event("Administrative Change", user="Administrator", details={"purged_guest_chats": len(names)})
