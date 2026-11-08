"""Small helpers shared by the copilot and the message analysis."""
from __future__ import annotations

import json
import re

import frappe
from frappe.utils import cint, strip_html

from thinknxg_support.integrations.ai import providers
from thinknxg_support.integrations.ai.engine import cfg, history_turns, redact, style_instructions

CONV = "Support Conversation Link"
MSG = "Support Portal Message"


class Unavailable(Exception):
    """The AI is switched off, has no budget left, or the feature is disabled."""


def require(feature: str | None = None):
    c = cfg()
    if not cint(c.enable_ai) and feature != "copilot":
        raise Unavailable("AI is switched off in Support AI Settings.")
    if not (c.api_key or c.provider == "OpenAI Compatible" and c.api_base_url):
        raise Unavailable("No AI provider is configured in Support AI Settings.")
    if feature and not cint(c.get({"copilot": "enable_copilot", "analysis": "analyze_messages",
                                   "summary": "summary_on_handoff"}.get(feature, feature))):
        raise Unavailable(f"The {feature} feature is switched off in Support AI Settings.")
    if not providers.budget_left():
        raise Unavailable("Today's AI budget has been used.")
    return c


def transcript(conv_name: str, limit: int | None = None, include_internal: bool = False) -> str:
    """The conversation as plain, redacted lines, oldest first."""
    filters = {"conversation": conv_name}
    if not include_internal:
        filters["is_internal"] = 0
    rows = frappe.get_all(MSG, filters=filters, fields=["direction", "content", "sender_type", "is_internal"],
                          order_by="creation desc", limit=limit or history_turns() * 2)
    lines = []
    for r in reversed(rows):
        text = redact(strip_html(r.content or "")).strip()
        if not text:
            continue
        who = "Customer" if r.direction == "Inbound" else ("Internal note" if cint(r.is_internal) else
                                                            (r.sender_type or "Agent"))
        lines.append(f"{who}: {text[:1200]}")
    return "\n".join(lines)


def call(kind: str, system: str, user: str, conversation: str | None = None, max_tokens: int = 500,
         temperature: float = 0.3) -> str:
    """One completion, logged in the usage log under `kind`. Raises Unavailable on provider errors."""
    try:
        r = providers.complete(system, [{"role": "user", "content": user}], max_tokens=max_tokens, temperature=temperature)
    except providers.AIError as e:
        providers.log_usage(kind=kind, status="Error", conversation=conversation, error=str(e))
        raise Unavailable(str(e)) from e
    providers.log_usage(kind=kind, result=r, conversation=conversation)
    return (r.get("text") or "").strip()


def parse_json(text: str):
    """The first JSON object or array in a model reply (models sometimes wrap it in prose or fences)."""
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    for opener, closer in (("{", "}"), ("[", "]")):
        start, end = text.find(opener), text.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except ValueError:
                continue
    return None


def style() -> str:
    return style_instructions(cfg())
