"""Usage limits per site.

The hosting operator sets the plan in site_config.json, which a site's administrators cannot change:
    "thinknxg_support_limits": {"ai_tokens_per_month": 2000000, "guest_chats_per_day": 500, ...}
Administrators can set lower limits in Support Usage Limits. The limit in force is the lower of the two; no value
means no limit. Checks run where the usage happens (new guest chat, AI call, new document, crawl).
"""
from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, get_first_day, nowdate

KEYS = {"ai_tokens_per_month": "AI tokens per month", "guest_chats_per_day": "Guest chats per day",
        "knowledge_documents": "Knowledge documents", "knowledge_storage_mb": "Knowledge document storage (MB)",
        "websites": "Crawled websites", "crawled_pages": "Crawled pages"}
SETTINGS = "Support Usage Limits"


class LimitReached(frappe.ValidationError):
    pass


def plan() -> dict:
    raw = frappe.conf.get("thinknxg_support_limits") or {}
    out = {}
    for k in KEYS:
        v = raw.get(k) if isinstance(raw, dict) else None
        if v is not None and cint(v) >= 0:
            out[k] = cint(v)
    return out


def limit(key: str) -> int | None:
    cap = plan().get(key)
    try:
        own = cint(frappe.db.get_single_value(SETTINGS, key))
    except Exception:
        own = 0
    values = [v for v in (cap, own if own > 0 else None) if v is not None]
    return min(values) if values else None


def used(key: str) -> int:
    if key == "ai_tokens_per_month":
        cache_key = "thinknxg_support:ai_tokens_month"
        val = frappe.cache.get_value(cache_key)
        if val is None:
            val = frappe.db.sql("select coalesce(sum(total_tokens),0) from `tabSupport AI Usage Log` where creation >= %s",
                                (get_first_day(nowdate()),))[0][0]
            frappe.cache.set_value(cache_key, int(val), expires_in_sec=300)
        return int(val)
    if key == "guest_chats_per_day":
        return frappe.db.count("Support Conversation Link", {"is_guest": 1, "creation": [">=", nowdate()]})
    if key == "knowledge_documents":
        return frappe.db.count("Support Knowledge Document") if _exists("Support Knowledge Document") else 0
    if key == "knowledge_storage_mb":
        if not _exists("Support Knowledge Document"):
            return 0
        files = frappe.get_all("Support Knowledge Document", pluck="file")
        size = sum(cint(s) for s in frappe.get_all("File", filters={"file_url": ["in", files or [""]]}, pluck="file_size"))
        return round(size / (1024 * 1024))
    if key == "websites":
        return frappe.db.count("Support Knowledge Website") if _exists("Support Knowledge Website") else 0
    if key == "crawled_pages":
        return frappe.db.count("Support Knowledge Web Page", {"status": "Active"}) if _exists("Support Knowledge Web Page") else 0
    return 0


def _exists(doctype):
    return frappe.db.exists("DocType", doctype)


def remaining(key: str) -> int | None:
    lim = limit(key)
    return None if lim is None else max(lim - used(key), 0)


def check(key: str, adding: int = 1, message: str | None = None):
    lim = limit(key)
    if lim is None:
        return
    if used(key) + adding > lim:
        from thinknxg_support.audit import log_event

        log_event("Rate Limit", severity="Warning", details={"limit": key, "allowed": lim}, user="Administrator")
        raise LimitReached(message or _("This site has reached its limit for {0} ({1}).").format(_(KEYS[key]).lower(), lim))


def ai_allowed() -> bool:
    lim = limit("ai_tokens_per_month")
    return lim is None or used("ai_tokens_per_month") < lim


def status() -> list[dict]:
    p = plan()
    return [{"key": k, "label": _(label), "used": used(k), "limit": limit(k), "plan": p.get(k)} for k, label in KEYS.items()]
