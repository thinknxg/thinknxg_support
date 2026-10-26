"""Per-user sliding window rate limiter backed by Redis (frappe.cache)."""
import time

import frappe
from frappe import _
from frappe.utils import cint


def check(bucket: str, limit: int | None = None, window: int = 60):
    """Guests are limited per IP address; logged-in users per account."""
    limit = cint(limit) or 30
    user = frappe.session.user or "Guest"
    if user == "Guest":
        user = "ip:" + (getattr(frappe.local, "request_ip", None) or "unknown")
    key = f"thinknxg_support:rl:{bucket}:{user}:{int(time.time() // window)}"
    cache = frappe.cache
    count = cache.incrby(key, 1) if hasattr(cache, "incrby") else cache.incr(key)
    if cint(count) == 1:
        cache.expire(key, window)
    if cint(count) > limit:
        from thinknxg_support.audit import log_event

        log_event("Rate Limit", severity="Warning", details={"bucket": bucket, "count": count})
        frappe.throw(_("Too many requests. Please wait a moment and try again."), frappe.TooManyRequestsError)
