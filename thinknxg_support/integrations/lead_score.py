"""Optional AI lead score (0 to 100, with short reasons) from the chat. Support AI Settings > Lead Score; off by
default. Uses the existing provider, daily budget, site limits, usage log and contact-detail redaction."""
from __future__ import annotations

import frappe
from frappe.utils import cint

CONV = "Support Conversation Link"
SYSTEM = ("You score sales leads from a customer chat. Reply with JSON only: {\"score\": 0-100, \"reasons\": [up to 3 "
          "short reasons]}. High: clear need, budget or timeline, decision maker, asks for price or a demo. Low: "
          "support question only, no buying interest. Judge only from the chat.")


def enabled() -> bool:
    c = frappe.get_cached_doc("Support AI Settings")
    return bool(cint(c.get("enable_lead_scoring")) and c.get("model"))


def queue(conversation: str):
    if enabled():
        frappe.enqueue("thinknxg_support.integrations.lead_score.score", queue="short", enqueue_after_commit=True,
                       conversation=conversation)


def score(conversation: str) -> dict | None:
    if not enabled():
        return None
    from thinknxg_support.integrations.ai import common

    try:
        transcript = common.transcript(conversation, 30, False)
        raw = common.call("Lead Score", SYSTEM, transcript, conversation=conversation, max_tokens=200, temperature=0)
        data = common.parse_json(raw) or {}
    except Exception:
        frappe.log_error(title="thinkNXG Support: lead score failed")
        return None
    if not isinstance(data, dict) or "score" not in data:
        return None
    value = min(max(cint(data.get("score")), 0), 100)
    reasons = [str(r)[:120] for r in (data.get("reasons") or []) if r][:3]
    frappe.db.set_value(CONV, conversation, {"lead_score": value, "lead_score_reasons": "\n".join(reasons) or None},
                        update_modified=False)
    return {"score": value, "reasons": reasons}
