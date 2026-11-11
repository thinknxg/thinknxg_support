"""WhatsApp Cloud API (Meta) adapter.

Inbound: webhook -> signature check (X-Hub-Signature-256 with the App Secret) -> background job per
message, de-duplicated by WhatsApp message id. Outbound: agent replies are queued and sent as text
while the 24-hour customer service window is open, or as the configured approved template after it
closes. Delivery receipts update each message's status. Numbers are matched to Contacts only when
exactly one Contact owns the number.
"""
from __future__ import annotations

import hashlib
import hmac
import html as html_lib
import json
import re

import frappe
import requests
from frappe import _
from frappe.utils import add_to_date, cint, get_datetime, now_datetime

from thinknxg_support.audit import log_event
from thinknxg_support.integrations import conversations
from thinknxg_support.utils import settings

GRAPH = "https://graph.facebook.com"
CONV = "Support Conversation Link"
MSG = "Support Portal Message"
STATUS_RANK = {"Pending": 0, "Sent": 1, "Delivered": 2, "Read": 3}
WINDOW_CLOSED_CODES = {131047, 131026}
MEDIA_TYPES = {"image", "document", "audio", "video", "sticker"}
MAX_TEXT = 4096


class WhatsAppError(Exception):
    def __init__(self, message, code=None, retryable=False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


def _secret(field: str) -> str | None:
    try:
        return frappe.get_single("Support Portal Settings").get_password(field, raise_exception=False)
    except Exception:
        return None


def available() -> bool:
    s = settings()
    return bool(s.enable_whatsapp and s.whatsapp_phone_number_id and _secret("whatsapp_access_token"))


def normalize(number: str | None) -> str:
    return re.sub(r"\D", "", number or "").lstrip("0")


def verify_signature(raw: bytes, header: str | None) -> bool:
    secret = _secret("whatsapp_app_secret")
    if not secret or not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), raw or b"", hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.split("=", 1)[1].strip())


def verify_subscription(mode: str | None, token: str | None) -> bool:
    expected = _secret("whatsapp_verify_token")
    return bool(mode == "subscribe" and expected and token and hmac.compare_digest(token, expected))


# ------------------------------------------------------------------ Graph API
def _api(path: str, *, method="POST", json=None, stream=False, absolute=False):
    s = settings()
    url = path if absolute else f"{GRAPH}/{s.whatsapp_api_version or 'v22.0'}/{path.lstrip('/')}"
    headers = {"Authorization": f"Bearer {_secret('whatsapp_access_token')}"}
    try:
        r = requests.request(method, url, json=json, headers=headers, timeout=20, stream=stream)
    except requests.RequestException as e:
        raise WhatsAppError(f"network: {e.__class__.__name__}", retryable=True)
    if stream:
        if r.status_code >= 400:
            raise WhatsAppError(f"media download failed ({r.status_code})", retryable=r.status_code >= 500)
        return r
    try:
        data = r.json()
    except ValueError:
        data = {}
    if r.status_code >= 400 or "error" in data:
        err = data.get("error") or {}
        code = err.get("code")
        detail = (err.get("error_data") or {}).get("details") or err.get("message") or f"HTTP {r.status_code}"
        raise WhatsAppError(str(detail)[:500], code=code, retryable=r.status_code >= 500 or code in (4, 80007, 130429))
    return data


def _send(payload: dict) -> str:
    s = settings()
    payload = {"messaging_product": "whatsapp", "recipient_type": "individual", **payload}
    data = _api(f"{s.whatsapp_phone_number_id}/messages", json=payload)
    return (data.get("messages") or [{}])[0].get("id")


def reply_context_of(message: dict, conversation: str | None = None) -> str | None:
    """1.14: the message the customer replied to on WhatsApp (their "reply" bubble), when we know it."""
    ctx = (message.get("context") or {}).get("id")
    if not ctx:
        return None
    filters = {"external_message_id": ctx}
    if conversation:
        filters["conversation"] = conversation
    return frappe.db.get_value(MSG, filters, "name")


WA_MEDIA_LIMIT = {"image": 5, "audio": 16, "document": 100}


def _upload_media(filename: str, content: bytes, mime: str) -> str:
    """Upload a file to the Cloud API; returns the media id to send."""
    s = settings()
    url = f"{GRAPH}/{s.whatsapp_api_version or 'v22.0'}/{s.whatsapp_phone_number_id}/media"
    try:
        r = requests.post(url, headers={"Authorization": f"Bearer {_secret('whatsapp_access_token')}"},
                          data={"messaging_product": "whatsapp", "type": mime}, files={"file": (filename, content, mime)},
                          timeout=60)
    except requests.RequestException as e:
        raise WhatsAppError(f"network: {e.__class__.__name__}", retryable=True)
    try:
        data = r.json()
    except ValueError:
        data = {}
    if r.status_code >= 400 or not data.get("id"):
        err = data.get("error") or {}
        raise WhatsAppError(str(err.get("message") or f"media upload failed (HTTP {r.status_code})")[:500],
                            retryable=r.status_code >= 500)
    return data["id"]


def _media_payload(msg, caption: str) -> dict | None:
    """The media part of an outgoing message (image, audio or document), uploaded first."""
    if not msg.attachment:
        return None
    import mimetypes

    from thinknxg_support.integrations import messaging

    fname = frappe.db.get_value("File", {"file_url": msg.attachment}, "name")
    if not fname:
        return None
    f = frappe.get_doc("File", fname)
    from thinknxg_support.utils import file_bytes

    content = file_bytes(f)
    kind = messaging.attachment_kind(msg.attachment)
    wa_type = {"image": "image", "audio": "audio"}.get(kind, "document")
    if wa_type == "image" and not messaging.image_ok(content, msg.attachment):
        wa_type = "document"
    if len(content) > WA_MEDIA_LIMIT[wa_type] * 1024 * 1024:
        raise WhatsAppError(_("The file is too large for WhatsApp ({0} MB at most).").format(WA_MEDIA_LIMIT[wa_type]))
    mime = mimetypes.guess_type(f.file_name)[0] or "application/octet-stream"
    if wa_type == "audio" and messaging.ext_of(f.file_name) in ("ogg", "oga", "opus"):
        mime = "audio/ogg"
    elif wa_type == "audio" and messaging.ext_of(f.file_name) not in ("m4a", "mp4", "aac", "mp3"):
        wa_type = "document"  # WhatsApp plays only OGG Opus, AAC, MP4 audio and MP3; browser WebM goes as a file
    media = {"id": _upload_media(f.file_name, content, mime)}
    if wa_type in ("image", "document") and caption:
        media["caption"] = caption[:1024]
    if wa_type == "document":
        media["filename"] = f.file_name
    return {"type": wa_type, wa_type: media}


def send_reaction(message: str, emoji: str = ""):
    """1.14: an agent's reaction on the customer's WhatsApp message (empty emoji removes it)."""
    msg = frappe.db.get_value(MSG, message, ["conversation", "external_message_id"], as_dict=True)
    if not msg or not msg.external_message_id or not available():
        return
    to = frappe.db.get_value(CONV, msg.conversation, "whatsapp_number")
    try:
        _send({"to": to, "type": "reaction", "reaction": {"message_id": msg.external_message_id, "emoji": emoji or ""}})
    except WhatsAppError as e:
        log_event("Integration Error", severity="Warning", reference_doctype=CONV, reference_name=msg.conversation,
                  details=f"whatsapp reaction failed: {str(e)[:200]}", user="Administrator")


def _send_template(to: str, conv=None) -> str:
    s = settings()
    if not s.whatsapp_template_name:
        raise WhatsAppError(_("The 24-hour reply window has closed and no re-engagement template is set."))
    template = {"name": s.whatsapp_template_name, "language": {"code": s.whatsapp_template_language or "en"}}
    key = f"{s.whatsapp_template_name}-{s.whatsapp_template_language or 'en'}"
    if conv is not None and frappe.db.exists("Support WhatsApp Template", key):  # 1.17: fill its variables
        from thinknxg_support.integrations import wa_templates

        tpl = frappe.get_cached_doc("Support WhatsApp Template", key)
        if tpl.variables and tpl.status == "Approved" and tpl.category != "Marketing":
            try:
                prep = wa_templates.prepare(tpl, conv)
                wa_templates.check_complete(tpl, prep["values"])
                template["components"] = wa_templates.components(tpl, prep["values"])
            except wa_templates.TemplateError as e:
                raise WhatsAppError(str(e))
    return _send({"to": to, "type": "template", "template": template})


def _send_stored_template(to: str, msg) -> str:
    """1.17: a template an agent or a rule chose: exactly the components stored on the message."""
    t = json.loads(msg.wa_components)
    return _send({"to": to, "type": "template", "template": {
        "name": t["name"], "language": {"code": t["language"]}, "components": t.get("components") or []}})


def _failed(msg, err: WhatsAppError):
    """Store a failure with what the Meta code means, and stop offering a template Meta paused or disabled."""
    from thinknxg_support.integrations import wa_templates

    code = cint(err.code) if err.code else None
    msg.db_set({"delivery_status": "Failed", "delivery_error": (wa_templates.explain(code, str(err)) or str(err))[:500],
                "delivery_code": code})
    if msg.get("wa_template"):
        wa_templates.on_send_error(msg.wa_template, code)


def html_to_text(html: str) -> str:
    text = re.sub(r"(?i)<br\s*/?>", "\n", html or "")
    text = re.sub(r"(?i)</p\s*>", "\n\n", text)
    text = re.sub(r"(?i)<li[^>]*>", "• ", text)
    text = re.sub(r"(?i)<(b|strong)>(.*?)</\1>", r"*\2*", text)
    text = re.sub(r"(?i)<(i|em)>(.*?)</\1>", r"_\2_", text)
    text = html_lib.unescape(frappe.utils.strip_html(text))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _chunks(text: str):
    while text:
        yield text[:MAX_TEXT]
        text = text[MAX_TEXT:]


def window_open(conv) -> bool:
    return bool(conv.whatsapp_window_expires and get_datetime(conv.whatsapp_window_expires) > now_datetime())


# ------------------------------------------------------------------ outbound
def deliver(message: str):
    """Background job: send one agent message to WhatsApp."""
    msg = frappe.get_doc(MSG, message)
    conv = frappe.get_doc(CONV, msg.conversation)
    key = f"wa-out:{msg.name}"
    if msg.delivery_status in ("Sent", "Delivered", "Read"):
        return
    try:
        if not available():
            raise WhatsAppError(_("WhatsApp is not enabled in Support Portal Settings."))
        to = conv.whatsapp_number
        if msg.get("wa_components"):  # 1.17: a chosen template goes out whether or not the window is open
            ext_id = _send_stored_template(to, msg)
            note = None
        elif window_open(conv):
            text = html_to_text(msg.content)
            ext_id = None
            context = None  # 1.14: WhatsApp shows the quoted message above the reply
            if msg.get("reply_to"):
                quoted = frappe.db.get_value(MSG, msg.reply_to, "external_message_id")
                context = {"message_id": quoted} if quoted else None
            try:
                media = _media_payload(msg, text)
                if media:
                    ext_id = _send({"to": to, **media, **({"context": context} if context else {})})
                    if media["type"] == "audio" and text:  # audio has no caption: the text follows
                        for part in _chunks(text):
                            ext_id = _send({"to": to, "type": "text", "text": {"body": part, "preview_url": False}})
                else:
                    for i, part in enumerate(_chunks(text or ".")):
                        payload = {"to": to, "type": "text", "text": {"body": part, "preview_url": False}}
                        if context and i == 0:
                            payload["context"] = context
                        ext_id = _send(payload)
                note = None
            except WhatsAppError as e:
                if e.code not in WINDOW_CLOSED_CODES:
                    raise
                ext_id = _send_template(to, conv)
                note = _("Sent the re-engagement template because WhatsApp reported the reply window as closed.")
        else:
            ext_id = _send_template(to, conv)
            note = _("The 24-hour reply window had closed, so the approved template was sent instead. "
                     "Your text reaches the customer after they reply.")
        msg.db_set({"external_message_id": ext_id, "delivery_status": "Sent", "delivery_error": note})
        _map(key, conv.name, "Outbound", msg.name, ext_id, "Delivered")
    except WhatsAppError as e:
        _failed(msg, e)
        _map(key, conv.name, "Outbound", msg.name, None, "Failed", ("network: " if e.retryable else "") + str(e))
        log_event("Integration Error", severity="Error", reference_doctype=CONV, reference_name=conv.name,
                  details=f"whatsapp send failed: {str(e)[:200]}", user="Administrator")
    conversations.publish_agent_event(conv, "delivery")


def _map(key, conv, direction, portal_message=None, external_id=None, state="Delivered", error=None):
    name = frappe.db.get_value("Support Message Mapping", {"dedupe_key": key})
    doc = frappe.get_doc("Support Message Mapping", name) if name else frappe.new_doc("Support Message Mapping")
    if not name:
        doc.dedupe_key = key
    doc.update({"conversation": conv, "provider": "WhatsApp", "direction": direction,
                "portal_message": portal_message, "external_message_id": external_id,
                "delivery_state": state, "attempts": cint(doc.attempts) + 1, "last_error": (error or "")[:1000] or None})
    doc.flags.ignore_permissions = True
    doc.save()


def retry_failed():
    if not available():
        return
    for row in frappe.get_all("Support Message Mapping",
                              filters={"provider": "WhatsApp", "direction": "Outbound", "delivery_state": "Failed",
                                       "attempts": ["<", 4], "last_error": ["like", "network:%"]},
                              fields=["portal_message"], limit=100):
        if row.portal_message:
            frappe.db.set_value(MSG, row.portal_message, "delivery_status", "Pending")
            deliver(row.portal_message)
            frappe.db.commit()


def send_test(to: str) -> str:
    if not available():
        frappe.throw(_("Fill in and save the WhatsApp settings first."))
    to = normalize(to)
    if len(to) < 8:
        frappe.throw(_("Enter the number with its country code."))
    try:
        if settings().whatsapp_template_name:
            _send_template(to)
            return _("Template '{0}' sent to +{1}.").format(settings().whatsapp_template_name, to)
        _send({"to": to, "type": "text", "text": {"body": "Test message from thinkNXG Support"}})
        return _("Test message sent to +{0}. Free text only arrives if that number messaged you in the last 24 hours.").format(to)
    except WhatsAppError as e:
        frappe.throw(_("WhatsApp rejected the message: {0}").format(e))


# ------------------------------------------------------------------ inbound
def handle_webhook(payload: dict):
    s = settings()
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            from thinknxg_support.integrations import wa_templates

            if change.get("field") in wa_templates.TEMPLATE_EVENTS:  # 1.17
                if str(entry.get("id") or "") == str(s.whatsapp_business_account_id or entry.get("id") or ""):
                    wa_templates.on_webhook(change["field"], change.get("value") or {})
                continue
            if change.get("field") != "messages":
                continue
            value = change.get("value") or {}
            if str((value.get("metadata") or {}).get("phone_number_id")) != str(s.whatsapp_phone_number_id):
                continue  # another number on the same app
            names = {c.get("wa_id"): (c.get("profile") or {}).get("name") for c in value.get("contacts") or []}
            for m in value.get("messages") or []:
                if not m.get("id"):
                    continue
                frappe.enqueue(process_inbound, queue="short", job_id=f"thinknxg-wa-in-{m['id']}",
                               deduplicate=True, enqueue_after_commit=True,
                               message=m, profile_name=names.get(m.get("from")))
            for st in value.get("statuses") or []:
                update_status(st)


def match_contact(wa_id: str) -> tuple[str | None, str | None, str | None]:
    """(contact, customer, user) when exactly one Contact owns the number; otherwise all None."""
    digits = normalize(wa_id)
    if len(digits) < 8:
        return None, None, None
    rows = frappe.get_all("Contact Phone", filters={"phone": ["like", f"%{digits[-7:]}%"], "parenttype": "Contact"},
                          fields=["parent", "phone"], limit=50)
    owners = {r.parent for r in rows if len(normalize(r.phone)) >= 8 and digits.endswith(normalize(r.phone))}
    if len(owners) != 1:
        return None, None, None
    contact = owners.pop()
    customers = frappe.get_all("Dynamic Link", filters={"parenttype": "Contact", "parent": contact,
                                                        "link_doctype": "Customer"}, pluck="link_name")
    user = frappe.db.get_value("Contact", contact, "user")
    return contact, (customers[0] if len(customers) == 1 else None), user


def _open_conversation(wa_id: str, profile_name: str | None):
    name = frappe.db.get_value(CONV, {"channel": "WhatsApp", "whatsapp_number": wa_id, "status": ["!=", "Closed"]},
                               "name", order_by="creation desc")
    if name:
        return frappe.get_doc(CONV, name)
    contact = customer = user = None
    if settings().whatsapp_link_contacts:
        contact, customer, user = match_contact(wa_id)
    conv = frappe.get_doc({
        "doctype": CONV,
        "subject": _("WhatsApp: {0}").format(profile_name or f"+{wa_id}"),
        "channel": "WhatsApp",
        "conversation_type": "Customer Chat",
        "status": "Open",
        "external_provider": "Portal Native",
        "whatsapp_number": wa_id,
        "whatsapp_profile_name": profile_name,
        "customer": customer,
        "contact": contact,
        "started_by": user,
        "last_activity_at": now_datetime(),
    })
    conv.insert(ignore_permissions=True)
    return conv


def _content(m: dict) -> tuple[str, dict | None]:
    t = m.get("type")
    if t == "text":
        return (m.get("text") or {}).get("body") or "", None
    if t == "button":
        return (m.get("button") or {}).get("text") or "", None
    if t == "interactive":
        i = m.get("interactive") or {}
        reply = i.get("button_reply") or i.get("list_reply") or {}
        return reply.get("title") or "", None
    if t == "location":
        loc = m.get("location") or {}
        label = " ".join(x for x in (loc.get("name"), loc.get("address")) if x)
        return f"{_('Location')}: {loc.get('latitude')}, {loc.get('longitude')} {label}".strip(), None
    if t == "contacts":
        people = [((c.get("name") or {}).get("formatted_name") or "") for c in m.get("contacts") or []]
        return f"{_('Shared contact')}: {', '.join(p for p in people if p)}", None
    if t in MEDIA_TYPES:
        media = m.get(t) or {}
        caption = media.get("caption") or ""
        return caption or f"[{_(t.title())}]", media
    return f"[{_('Unsupported message type')}: {t}]", None


def process_inbound(message: dict, profile_name: str | None = None):
    key = f"wa-in:{message.get('id')}"
    if frappe.db.exists("Support Message Mapping", {"dedupe_key": key}):
        return
    if message.get("type") == "reaction":  # 1.14: the customer's reaction on one of our messages
        from thinknxg_support.integrations import messaging

        r = message.get("reaction") or {}
        if r.get("message_id"):
            messaging.whatsapp_reaction(r["message_id"], r.get("emoji") or "")
        return
    wa_id = normalize(message.get("from"))
    profile_name = (profile_name or "").strip()[:80] or None
    conv = _open_conversation(wa_id, profile_name)
    text, media = _content(message)
    from thinknxg_support.integrations import wa_templates

    keyword = wa_templates.keyword(text) if message.get("type") == "text" else None
    frappe.flags.thinknxg_skip_reply = bool(keyword)  # STOP / START are for the opt-in list: no assistant answer
    try:
        result = conversations.add_inbound_message(
            conv, text, sender=conv.started_by, sender_name=profile_name or f"+{wa_id}",
            external_id=message.get("id"), allow_html=False, reopen=True,
            reply_to=reply_context_of(message, conv.name))
    finally:
        frappe.flags.thinknxg_skip_reply = False
    conv.db_set({"whatsapp_window_expires": add_to_date(now_datetime(), hours=24),
                 "whatsapp_profile_name": profile_name or conv.whatsapp_profile_name}, update_modified=False)
    if media and result.get("name") and not result.get("duplicate"):
        try:
            _attach_media(result["name"], media, message.get("type"))
        except Exception as e:
            log_event("Integration Error", severity="Warning", reference_doctype=CONV, reference_name=conv.name,
                      details=f"whatsapp media download failed: {str(e)[:200]}", user="Administrator")
    _map(key, conv.name, "Inbound", result.get("name"), message.get("id"), "Delivered")
    _mark_read(message.get("id"))
    if keyword:
        _opt_keyword(conv, wa_id, text)
        return
    _auto_reply(conv)


def _opt_keyword(conv, wa_id: str, text: str):
    from thinknxg_support.integrations import wa_templates

    out = wa_templates.on_inbound(conv, wa_id, text)
    if out and "\n" in out:  # the confirmation the customer gets (free text: they just wrote, the window is open)
        conversations.post_agent_message(conv, out.split("\n", 1)[1], sender="Administrator", source="system",
                                         sender_type="System", response_source="Opt-in list")


def _attach_media(msg_name: str, media: dict, kind: str):
    meta = _api(media["id"], method="GET")
    max_mb = cint(settings().max_attachment_mb) or 10
    if cint(meta.get("file_size")) > max_mb * 1024 * 1024:
        raise WhatsAppError(f"media larger than {max_mb} MB")
    content = _api(meta["url"], method="GET", stream=True, absolute=True).content
    mime = (meta.get("mime_type") or "").split(";")[0]
    ext = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "application/pdf": "pdf",
           "audio/ogg": "ogg", "audio/mpeg": "mp3", "audio/mp4": "m4a", "video/mp4": "mp4"}.get(mime, "bin")
    fname = media.get("filename") or f"whatsapp-{kind}-{msg_name[:8]}.{ext}"
    f = frappe.get_doc({"doctype": "File", "file_name": fname, "content": content, "is_private": 1,
                        "attached_to_doctype": MSG, "attached_to_name": msg_name})
    f.flags.ignore_permissions = True
    f.insert()
    frappe.db.set_value(MSG, msg_name, "attachment", f.file_url)


def _mark_read(message_id: str | None):
    if not message_id or not available():
        return
    try:
        _send({"status": "read", "message_id": message_id})
    except Exception:
        pass  # read receipts are best effort


def _auto_reply(conv):
    from thinknxg_support.integrations.live_chat import is_online

    s = settings()
    conv.reload()
    if s.whatsapp_auto_reply and not conv.whatsapp_auto_replied and not is_online():
        conv.db_set("whatsapp_auto_replied", 1, update_modified=False)
        conversations.post_agent_message(conv, s.whatsapp_auto_reply, sender="Administrator", source="system",
                                         sender_type="System", response_source="Auto Reply")


def update_status(st: dict):
    ext_id = st.get("id")
    status = (st.get("status") or "").title()
    if not ext_id or status not in ("Sent", "Delivered", "Read", "Failed"):
        return
    row = frappe.db.get_value(MSG, {"external_message_id": ext_id}, ["name", "delivery_status", "conversation"],
                              as_dict=True)
    if not row:
        return
    if status == "Failed":
        err = (st.get("errors") or [{}])[0]
        detail = (err.get("error_data") or {}).get("details") or err.get("title") or _("Delivery failed")
        from thinknxg_support.integrations import wa_templates

        code = cint(err.get("code")) or None
        frappe.db.set_value(MSG, row.name, {"delivery_status": "Failed", "delivery_code": code,
                                            "delivery_error": (wa_templates.explain(code, str(detail)) or str(detail))[:500]})
        tpl = frappe.db.get_value(MSG, row.name, "wa_template")
        if tpl:
            wa_templates.on_send_error(tpl, code)
    elif STATUS_RANK.get(status, 0) > STATUS_RANK.get(row.delivery_status or "Pending", 0):
        frappe.db.set_value(MSG, row.name, "delivery_status", status)
    else:
        return
    conversations.publish_agent_event(frappe._dict(name=row.conversation, channel="WhatsApp"), "delivery")
