"""Rule-based chatbot: welcome buttons, keyword / phrase / regex rules, button flows and handoff words."""
from __future__ import annotations

import json
import re

import frappe
from frappe.utils import strip_html

CHANNEL_FIELD = {"Live Chat": "channel_live_chat", "WhatsApp": "channel_whatsapp", "Portal": "channel_portal"}


def active_bot(channel: str):
    field = CHANNEL_FIELD.get(channel or "Portal")
    name = frappe.db.get_value("Support Chatbot", {"enabled": 1, field: 1}, "name", order_by="modified desc")
    return frappe.get_cached_doc("Support Chatbot", name) if name else None


def parse_buttons(text: str | None) -> list[dict]:
    out = []
    for line in (text or "").splitlines():
        if "|" in line:
            label, target = (x.strip() for x in line.split("|", 1))
            if label and target:
                out.append({"label": label[:60], "payload": target[:140]})
    return out[:8]


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", strip_html(text or "")).strip().casefold()


def wants_human(bot, text: str) -> bool:
    words = [w.strip().casefold() for w in ((bot.handoff_keywords if bot else "") or "").split(",") if w.strip()]
    t = _norm(text)
    if len(t) > 80:  # long messages are questions, not requests for a person
        return False
    return any(re.search(rf"(?<![\w]){re.escape(w)}(?![\w])", t) for w in words)


def rule_by_name(bot, name: str):
    name = (name or "").strip().casefold()
    return next((r for r in bot.rules if r.enabled and (r.rule_name or "").strip().casefold() == name), None)


def match(bot, text: str, payload: str | None = None):
    if not bot:
        return None
    if payload:
        return rule_by_name(bot, payload)
    t = _norm(text)[:2000]
    for r in sorted((r for r in bot.rules if r.enabled), key=lambda r: -(r.priority or 0)):
        trig = (r.trigger or "").strip()
        if r.trigger_type == "Button Only" or not trig:
            continue
        if r.trigger_type == "Regex":
            try:
                if re.search(trig, t, flags=re.IGNORECASE):
                    return r
            except re.error:
                continue
        elif r.trigger_type == "Exact Phrase":
            if t == _norm(trig):
                return r
        else:
            words = [w.strip().casefold() for w in trig.split(",") if w.strip()]
            hits = [bool(re.search(rf"(?<![\w]){re.escape(w)}(?![\w])", t)) for w in words]
            if (r.trigger_type == "All Keywords" and words and all(hits)) or (r.trigger_type == "Keywords" and any(hits)):
                return r
    return None


def option_from_number(conv, text: str) -> str | None:
    """WhatsApp shows buttons as a numbered list: map "2" back to the second button."""
    t = _norm(text)
    if not t.isdigit() or not conv.get("bot_options"):
        return None
    try:
        opts = json.loads(conv.bot_options)
    except ValueError:
        return None
    i = int(t) - 1
    return opts[i]["payload"] if 0 <= i < len(opts) else None


def welcome_for_widget(channel: str = "Live Chat") -> dict | None:
    bot = active_bot(channel)
    if not bot:
        return None
    return {"message": bot.welcome_message, "buttons": parse_buttons(bot.welcome_buttons), "name": bot.display_name}
