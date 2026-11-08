"""Collect a visitor's details in the chat, one question at a time, then create the lead.

Started by a chatbot rule ("Collect Details"), an automation rule (outside chat hours) or an agent. While it runs,
the visitor's answers are taken by this, not by the assistant; "cancel" stops it. Agents who take the chat over
are not interrupted: it only runs while the assistant or the queue has the chat.
"""
from __future__ import annotations

import json
import re

import frappe
from frappe import _
from frappe.utils import strip_html

CONV = "Support Conversation Link"
EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
STOP = {"cancel", "stop", "no", "إلغاء", "لا"}
SKIP = {"skip", "-", "none", "no", "تخطي"}


def questions():
    return [("name", _("May I have your name?"), True), ("email", _("What is your e-mail address?"), True),
            ("phone", _("And a phone number? (or type skip)"), False),
            ("company", _("Which company are you with? (or type skip)"), False)]


def _state(conv) -> dict | None:
    raw = frappe.db.get_value(CONV, conv.name, "lead_capture_json")
    try:
        st = json.loads(raw) if raw else None
    except ValueError:
        st = None
    return st if isinstance(st, dict) and st.get("active") else None


def _save(conv, st):
    frappe.db.set_value(CONV, conv.name, "lead_capture_json", json.dumps(st) if st else None, update_modified=False)


def _say(conv, text: str):
    from thinknxg_support.integrations.ai import engine, language

    engine.post(conv, f"<p>{frappe.utils.escape_html(language.localize(conv, text))}</p>", "Bot", "Lead capture")


def _next(conv, st) -> bool:
    for field, question, _required in questions():
        if field not in st["values"] and field not in st.get("skipped", []):
            st["asking"] = field
            _save(conv, st)
            _say(conv, question)
            return True
    return False


def start(conv, intro: str | None = None, source: str = "rule") -> bool:
    from thinknxg_support.integrations import crm

    if _state(conv) or conv.get("lead") or not crm.target():
        return False
    known = {k: v for k, v in crm.details(conv).items() if v}
    st = {"active": 1, "values": known, "skipped": [], "source": source, "asking": None}
    if intro:
        _say(conv, intro)
    if not _next(conv, st):
        return finish(conv, st)
    return True


def active(conv) -> bool:
    return bool(_state(conv))


def consume(conv, text: str) -> bool:
    """Take the visitor's answer. False when no capture is running (the message goes on as usual)."""
    if conv.get("handling") == "Agent":
        return False
    st = _state(conv)
    if not st:
        return False
    answer = " ".join(strip_html(text or "").split())
    field = st.get("asking")
    if answer.casefold() in STOP and field in ("name", "email"):
        _save(conv, None)
        _say(conv, _("No problem. How else can we help?"))
        return True
    required = {f: r for f, _q, r in questions()}.get(field, False)
    if not required and answer.casefold() in SKIP:
        st.setdefault("skipped", []).append(field)
    elif field == "email":
        m = EMAIL.search(answer)
        if not m:
            _say(conv, _("That does not look like an e-mail address. Please type it again, e.g. name@example.com"))
            return True
        st["values"]["email"] = m.group(0).lower()
    elif field == "phone":
        digits = "".join(c for c in answer if c.isdigit())
        if len(digits) < 6:
            _say(conv, _("Please type the number with its country code, or type skip."))
            return True
        st["values"]["phone"] = ("+" if answer.strip().startswith("+") else "") + digits
    elif field:
        st["values"][field] = answer[:140]
    if not _next(conv, st):
        finish(conv, st)
    return True


def finish(conv, st) -> bool:
    from thinknxg_support.integrations import crm

    _save(conv, None)
    v = st.get("values", {})
    updates = {}
    if v.get("name") and conv.get("is_guest") and not conv.get("guest_name"):
        updates["guest_name"] = v["name"][:140]
    if v.get("email") and not conv.get("guest_email"):
        updates["guest_email"] = v["email"]
    if v.get("phone") and not conv.get("guest_phone") and conv.get("channel") != "WhatsApp":
        updates["guest_phone"] = v["phone"]
    if updates:
        frappe.db.set_value(CONV, conv.name, updates, update_modified=False)
    try:
        crm.create_lead(frappe.get_doc(CONV, conv.name), v, actor="Administrator")
        _say(conv, _("Thank you! Our team will get back to you soon."))
        return True
    except frappe.ValidationError:
        _say(conv, _("Thank you. Our team will get back to you."))
        return False
