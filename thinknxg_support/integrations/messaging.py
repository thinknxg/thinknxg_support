"""Rules for changing chat messages after they are sent, and for files in chats.

Who may do what (checked here for every client):
* Edit: your own messages. Customers and visitors within the edit window (Support Portal Settings, default 5
  minutes) while the chat is open; staff while the chat is open; internal notes always. WhatsApp messages cannot be
  changed once sent. Every earlier version is kept (Support Message Revision) and shown to staff.
* Remove: the same as edit, plus support managers may remove any customer-visible message (moderation). Removed
  messages are hidden from customers ("Message removed") and kept, with their text, for staff and audit.
* React: anyone in the conversation, on messages they can see, with a small fixed set of emoji.
* Reply to: a message of the same conversation; customer-visible replies can only quote customer-visible messages.
* Files: visitors may attach files when Support Portal Settings allows it (same types and size as portal
  customers); voice notes are audio files checked by their content. Every download is authorised again.
"""
from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import add_to_date, cint, get_datetime, now_datetime, strip_html

from thinknxg_support import ratelimit
from thinknxg_support.utils import settings

CONV = "Support Conversation Link"
MSG = "Support Portal Message"
REV = "Support Message Revision"
REACTIONS = ["👍", "❤️", "😂", "😮", "😢", "🙏"]
IMAGE_EXT = {"png": (b"\x89PNG",), "jpg": (b"\xff\xd8\xff",), "jpeg": (b"\xff\xd8\xff",), "gif": (b"GIF87a", b"GIF89a"),
             "webp": (b"RIFF",)}
AUDIO_EXT = {"webm", "ogg", "oga", "opus", "m4a", "mp4", "aac", "mp3", "wav"}
MANAGERS = ("Support Manager", "Support Portal Administrator", "System Manager")
MAX_VOICE_MB = 8


class Actor:
    """Who is acting: staff (a desk user), customer (a portal user), guest (a visitor with a chat token) or
    whatsapp (the customer on WhatsApp, through the webhook)."""

    def __init__(self, kind: str, user: str | None = None, conversation: str | None = None, name: str | None = None):
        self.kind, self.user, self.conversation, self.name = kind, user, conversation, name

    @property
    def key(self) -> str:
        return {"staff": f"u:{self.user}", "customer": f"u:{self.user}", "guest": f"g:{self.conversation}",
                "whatsapp": "c:wa"}[self.kind]

    @property
    def label(self) -> str:
        return self.name or self.user or _("Visitor")

    @property
    def manager(self) -> bool:
        return self.kind == "staff" and bool(set(MANAGERS) & set(frappe.get_roles(self.user)))


def staff() -> Actor:
    return Actor("staff", user=frappe.session.user,
                 name=frappe.db.get_value("User", frappe.session.user, "full_name") or frappe.session.user)


def guest(conv) -> Actor:
    return Actor("guest", conversation=conv.name, name=conv.get("guest_name"))


def customer(pu) -> Actor:
    return Actor("customer", user=pu.user, name=getattr(pu, "full_name", None))


# ------------------------------------------------------------------ settings
def edit_minutes() -> int:
    return max(0, cint(settings().get("customer_edit_minutes") if settings().get("customer_edit_minutes") is not None else 5))


def customer_edits_on() -> bool:
    v = settings().get("allow_customer_edits")
    return True if v is None else bool(cint(v))


def reactions_on() -> bool:
    v = settings().get("allow_reactions")
    return True if v is None else bool(cint(v))


def guest_uploads_on() -> bool:
    return bool(cint(settings().get("allow_guest_uploads")))


def voice_on() -> bool:
    v = settings().get("allow_voice_notes")
    return True if v is None else bool(cint(v))


def max_voice_seconds() -> int:
    return min(max(cint(settings().get("max_voice_seconds")) or 120, 10), 600)


def capabilities() -> dict:
    return {"edit_minutes": edit_minutes() if customer_edits_on() else 0, "reactions": REACTIONS if reactions_on() else [],
            "guest_uploads": guest_uploads_on(), "voice": voice_on(), "max_voice_seconds": max_voice_seconds()}


# ------------------------------------------------------------------ files
def ext_of(url: str | None) -> str:
    name = (url or "").split("?", 1)[0].rsplit("/", 1)[-1]
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def attachment_kind(url: str | None) -> str | None:
    if not url:
        return None
    ext = ext_of(url)
    return "image" if ext in IMAGE_EXT else "audio" if ext in AUDIO_EXT else "file"


def _audio_ok(content: bytes) -> bool:
    head = content[:16]
    return (head.startswith(b"\x1a\x45\xdf\xa3") or head.startswith(b"OggS") or head[4:8] == b"ftyp"
            or head.startswith(b"ID3") or head[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2", b"\xff\xf1", b"\xff\xf9")
            or (head.startswith(b"RIFF") and content[8:12] == b"WAVE"))


def save_voice(filename: str, content: bytes, msg_name: str) -> str:
    """Voice notes: audio only, checked by content (not just the name), private, attached to the message."""
    import os

    ext = ext_of(filename)
    if ext not in AUDIO_EXT or not _audio_ok(content):
        frappe.throw(_("A voice note must be an audio recording."))
    if len(content) > MAX_VOICE_MB * 1024 * 1024:
        frappe.throw(_("The voice note is too long."))
    f = frappe.get_doc({"doctype": "File", "file_name": os.path.basename(filename), "content": content, "is_private": 1,
                        "attached_to_doctype": MSG, "attached_to_name": msg_name})
    f.flags.ignore_permissions = True
    f.insert()
    return f.file_url


def image_ok(content: bytes, url: str) -> bool:
    ext = ext_of(url)
    sigs = IMAGE_EXT.get(ext)
    if not sigs or not content.startswith(sigs):
        return False
    return ext != "webp" or content[8:12] == b"WEBP"


def stream_attachment(msg):
    """Send the message's file (as a download). Callers have already checked access."""
    if not msg.attachment or cint(msg.get("hidden")):
        frappe.throw(_("File not found."), frappe.DoesNotExistError)
    name = frappe.db.get_value("File", {"file_url": msg.attachment, "attached_to_doctype": MSG,
                                        "attached_to_name": msg.name}, "name") \
        or frappe.db.get_value("File", {"file_url": msg.attachment}, "name")
    if not name:
        frappe.throw(_("File not found."), frappe.DoesNotExistError)
    from thinknxg_support.utils import stream_file

    stream_file(name)


# ------------------------------------------------------------------ views
def reactions_of(raw) -> dict:
    try:
        data = json.loads(raw or "{}")
    except ValueError:
        return {}
    return {e: list(dict.fromkeys(v)) for e, v in data.items() if e in REACTIONS and isinstance(v, list) and v}


def reactions_view(raw, me_key: str | None = None) -> list[dict]:
    data = reactions_of(raw)
    return [{"emoji": e, "count": len(data[e]), "mine": bool(me_key and me_key in data[e])} for e in REACTIONS if e in data]


def excerpt(row) -> str:
    if cint(row.get("hidden")):
        return _("Message removed")
    text = " ".join(strip_html(row.get("content") or "").split())
    if not text and row.get("attachment"):
        kind = attachment_kind(row.attachment)
        text = _("Voice note") if kind == "audio" else _("Photo") if kind == "image" else _("File")
    return text[:140] + ("…" if len(text) > 140 else "")


def reply_view(name: str | None) -> dict | None:
    if not name:
        return None
    cache = frappe.local.__dict__.setdefault("thinknxg_reply_cache", {}) if hasattr(frappe.local, "__dict__") else {}
    if name in cache:
        return cache[name]
    row = frappe.db.get_value(MSG, name, ["name", "content", "attachment", "hidden", "sender_name", "direction",
                                          "sender_type", "is_internal"], as_dict=True)
    out = None
    if row:
        author = row.sender_name if row.direction == "Inbound" else ((row.sender_name or "").split(" ")[0] or _("Support"))
        out = {"id": row.name, "author": author, "excerpt": excerpt(row), "internal": bool(cint(row.is_internal))}
    cache[name] = out
    return out


# ------------------------------------------------------------------ rules
def _conv_closed(conversation: str) -> bool:
    return frappe.db.get_value(CONV, conversation, "status") == "Closed"


def owns(row, actor: Actor) -> bool:
    if actor.kind == "staff":
        return row.direction == "Outbound" and row.sender == actor.user and (row.get("sender_type") or "Agent") == "Agent"
    if actor.kind == "customer":
        return row.direction == "Inbound" and bool(row.sender) and row.sender == actor.user
    if actor.kind == "guest":
        return row.direction == "Inbound" and row.conversation == actor.conversation and not row.sender
    return False


def can_edit(row, actor: Actor, closed: bool | None = None) -> bool:
    return not _why_not(row, actor, closed, "edit")


def can_remove(row, actor: Actor, closed: bool | None = None) -> bool:
    return not _why_not(row, actor, closed, "remove")


def _why_not(row, actor: Actor, closed, action) -> str | None:
    if cint(row.get("hidden")):
        return _("This message was removed.")
    internal = cint(row.get("is_internal"))
    if actor.kind != "staff" and internal:
        return _("Message not found.")
    moderating = action == "remove" and actor.kind == "staff" and not internal and actor.manager
    if not owns(row, actor) and not moderating:
        return _("You can only change your own messages.")
    if row.get("channel") == "WhatsApp" and not internal and row.direction == "Outbound":
        return _("WhatsApp messages cannot be changed once they are sent.")
    if internal:
        return None
    closed = _conv_closed(row.conversation) if closed is None else closed
    if closed:
        return _("This conversation is closed.")
    if actor.kind in ("customer", "guest"):
        if not customer_edits_on():
            return _("Messages cannot be changed here.")
        if get_datetime(row.creation) < add_to_date(now_datetime(), minutes=-edit_minutes()):
            return _("Messages can only be changed within {0} minutes.").format(edit_minutes())
    return None


ROW_FIELDS = ["name", "conversation", "direction", "sender", "sender_name", "sender_type", "content", "attachment",
              "is_internal", "hidden", "creation", "channel", "reactions_json", "external_message_id"]


def _row(message: str, conversation: str | None):
    row = frappe.db.get_value(MSG, message, ROW_FIELDS, as_dict=True) if message else None
    if not row or (conversation and row.conversation != conversation):
        frappe.throw(_("Message not found."), frappe.DoesNotExistError)
    return row


def _changed(row):
    from thinknxg_support.integrations import conversations, realtime

    realtime.bump(row.conversation)
    conv = frappe.get_doc(CONV, row.conversation)
    conversations.publish_agent_event(conv, "message")


def _raven_sync(row, html: str):
    """Keep the copy in the agents' Raven channel in step (best effort)."""
    try:
        if not frappe.db.exists("DocType", "Raven Message"):
            return
        for ext in frappe.get_all("Support Message Mapping", filters={"portal_message": row.name, "provider": "Raven"},
                                  pluck="external_message_id"):
            if ext and frappe.db.exists("Raven Message", ext):
                frappe.db.set_value("Raven Message", ext, "text", html, update_modified=True)
    except Exception:
        frappe.log_error(title="thinkNXG Support: Raven copy not updated")


def edit(message: str, text: str, actor: Actor, conversation: str | None = None) -> dict:
    ratelimit.check("msg_edit", 30, 600)
    row = _row(message, conversation)
    why = _why_not(row, actor, None, "edit")
    if why:
        frappe.throw(why, frappe.PermissionError)
    from thinknxg_support.integrations.conversations import _text_to_html

    new = _text_to_html(text)
    if not strip_html(new).strip():
        frappe.throw(_("Write something, or remove the message instead."))
    if new == (row.content or ""):
        return {"name": row.name, "changed": False}
    frappe.get_doc({"doctype": REV, "message": row.name, "conversation": row.conversation, "content": row.content,
                    "edited_by": actor.label, "edited_on": now_datetime()}).insert(ignore_permissions=True)
    frappe.db.set_value(MSG, row.name, {"content": new, "edited_on": now_datetime()})
    _raven_sync(row, new)
    _changed(row)
    return {"name": row.name, "changed": True}


def remove(message: str, actor: Actor, conversation: str | None = None) -> dict:
    ratelimit.check("msg_edit", 30, 600)
    row = _row(message, conversation)
    why = _why_not(row, actor, None, "remove")
    if why:
        frappe.throw(why, frappe.PermissionError)
    frappe.db.set_value(MSG, row.name, {"hidden": 1, "hidden_by": actor.label, "hidden_on": now_datetime()})
    _raven_sync(row, f"<p><em>{_('Message removed by {0}').format(actor.label)}</em></p>")
    if not owns(row, actor):
        from thinknxg_support.audit import log_event

        log_event("Administrative Change", reference_doctype=MSG, reference_name=row.name,
                  details={"removed_message_of": row.direction})
    _changed(row)
    return {"name": row.name, "removed": True}


def react(message: str, emoji: str, actor: Actor, conversation: str | None = None) -> dict:
    if not reactions_on():
        frappe.throw(_("Reactions are switched off."), frappe.PermissionError)
    if emoji not in REACTIONS:
        frappe.throw(_("Choose one of the reactions offered."))
    ratelimit.check("msg_react", 60, 600)
    row = _row(message, conversation)
    if cint(row.is_internal) and actor.kind != "staff":
        frappe.throw(_("Message not found."), frappe.DoesNotExistError)
    if cint(row.hidden):
        frappe.throw(_("This message was removed."), frappe.PermissionError)
    data = reactions_of(row.reactions_json)
    users = data.setdefault(emoji, [])
    added = actor.key not in users
    if added:
        users.append(actor.key)
    else:
        users.remove(actor.key)
    frappe.db.set_value(MSG, row.name, "reactions_json", json.dumps({k: v for k, v in data.items() if v}) or None)
    if actor.kind == "staff" and row.channel == "WhatsApp" and row.direction == "Inbound" and row.external_message_id \
            and not cint(row.is_internal):
        frappe.enqueue("thinknxg_support.integrations.whatsapp.send_reaction", queue="short", enqueue_after_commit=True,
                       message=row.name, emoji=emoji if added else "")
    _changed(row)
    return {"name": row.name, "reactions": reactions_view(json.dumps(data), actor.key)}


def whatsapp_reaction(external_message_id: str, emoji: str | None):
    """A reaction the customer made on WhatsApp (one per person there; an empty emoji removes it)."""
    name = frappe.db.get_value(MSG, {"external_message_id": external_message_id}, "name")
    if not name:
        return
    row = _row(name, None)
    data = {e: [k for k in v if k != "c:wa"] for e, v in reactions_of(row.reactions_json).items()}
    if emoji:
        data.setdefault(emoji if emoji in REACTIONS else REACTIONS[0], []).append("c:wa")
    frappe.db.set_value(MSG, row.name, "reactions_json", json.dumps({k: v for k, v in data.items() if v}) or None)
    _changed(row)


def history(message: str, conversation: str) -> list[dict]:
    row = _row(message, conversation)
    return [{"text": strip_html(r.content or ""), "html": r.content, "edited_by": r.edited_by, "edited_on": str(r.edited_on)}
            for r in frappe.get_all(REV, filters={"message": row.name}, fields=["content", "edited_by", "edited_on"],
                                    order_by="edited_on asc")]


def reply_target(conversation: str, reply_to: str | None, customer_visible: bool) -> str | None:
    if not reply_to:
        return None
    row = frappe.db.get_value(MSG, reply_to, ["conversation", "is_internal"], as_dict=True)
    if not row or row.conversation != conversation:
        frappe.throw(_("The message you are replying to is not in this conversation."))
    if customer_visible and cint(row.is_internal):
        frappe.throw(_("A reply to the customer cannot quote an internal note."))
    return reply_to


def check_upload(actor_kind: str, files, voice_seconds) -> None:
    """Visitors: files only when allowed; voice notes when allowed. Rate limited."""
    if not files:
        return
    if voice_seconds:
        if not voice_on():
            frappe.throw(_("Voice notes are switched off."), frappe.PermissionError)
        if cint(voice_seconds) > max_voice_seconds() + 2:
            frappe.throw(_("Voice notes can be up to {0} seconds.").format(max_voice_seconds()))
    elif actor_kind == "guest" and not guest_uploads_on():
        frappe.throw(_("Files cannot be sent in this chat."), frappe.PermissionError)
    if actor_kind in ("guest", "customer"):
        ratelimit.check("chat_upload", 15, 3600)


def save_files(files, msg_name: str, voice_seconds=None) -> str | None:
    if not files:
        return None
    fname, data = files[0]
    if voice_seconds:
        url = save_voice(fname, data, msg_name)
        frappe.db.set_value(MSG, msg_name, {"attachment": url, "voice_seconds": cint(voice_seconds)},
                            update_modified=False)
        return url
    from thinknxg_support.utils import save_private_file

    saved = save_private_file(fname, data, MSG, msg_name)
    url = frappe.db.get_value("File", saved["name"], "file_url")
    frappe.db.set_value(MSG, msg_name, "attachment", url, update_modified=False)
    return url
