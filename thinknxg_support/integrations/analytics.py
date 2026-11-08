"""Read-only support metrics for managers. One indexed query per table and period, cached for five minutes.

Definitions (also shown on the page):
* AI resolved: closed without any person replying, after the assistant answered (or marked solved by the assistant).
* Human handled: a person replied (first_agent_reply_at), with or without the assistant first.
* AI resolution rate: AI resolved / conversations the assistant answered at least once.
* First response: from handoff (or from the start, when the chat went straight to people) to the first agent reply.
* Resolution time: from the start to closing.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict

import frappe
from frappe import _
from frappe.utils import add_days, add_to_date, cint, get_datetime, getdate, now_datetime, nowdate

CONV = "Support Conversation Link"
ASSIGN = "Support Chat Assignment"
FEEDBACK = "Support Chat Feedback"
USAGE = "Support AI Usage Log"
ALERT = "Support Agent Alert"
MANAGERS = ("System Manager", "Support Portal Administrator", "Support Manager")
MAX_ROWS = 50_000
CACHE_SECONDS = 300


def require_manager():
    if frappe.session.user == "Guest" or not set(MANAGERS) & set(frappe.get_roles()):
        frappe.throw(_("Support analytics are for support managers."), frappe.PermissionError)


def period(from_date=None, to_date=None):
    end = getdate(to_date or nowdate())
    start = getdate(from_date or add_days(end, -29))
    if start > end:
        start, end = end, start
    if (end - start).days > 366:
        start = add_days(end, -366)
    return start, end


def _filters(start, end, channel=None, queue=None, field="creation"):
    f = {field: ["between", [f"{start} 00:00:00", f"{end} 23:59:59.999999"]]}
    if channel:
        f["channel"] = channel
    if queue:
        f["queue"] = queue
    return f


def _secs(a, b):
    if not a or not b:
        return None
    s = (get_datetime(b) - get_datetime(a)).total_seconds()
    return s if s >= 0 else None


def _pct(values, q):
    v = sorted(x for x in values if x is not None)
    if not v:
        return None
    k = (len(v) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(v) - 1)
    return round(v[lo] + (v[hi] - v[lo]) * (k - lo), 1)


def _rate(n, d):
    return round(100.0 * n / d, 1) if d else None


def _cached(name, args, build):
    version = frappe.cache.get_value("thinknxg_support:analytics_version") or "0"
    key = "thinknxg_support:analytics:" + hashlib.sha1(json.dumps([name, version, args], default=str).encode()).hexdigest()
    hit = frappe.cache.get_value(key)
    if hit is not None:
        return hit
    out = build()
    frappe.cache.set_value(key, out, expires_in_sec=CACHE_SECONDS)
    return out


def refresh():
    frappe.cache.set_value("thinknxg_support:analytics_version", frappe.generate_hash(length=8))


def category(c) -> str:
    if c.first_agent_reply_at:
        return "human"
    if cint(c.resolved_by_assistant) or (cint(c.ai_replies) and c.status == "Closed" and not c.handoff_at):
        return "ai"
    return "other"


CONV_FIELDS = ["name", "creation", "channel", "queue", "status", "handling", "handoff_at", "first_agent_reply_at",
               "closed_on", "resolved_by_assistant", "ai_replies", "assigned_agent", "sentiment", "intent",
               "customer_language", "handoff_reason", "is_guest", "lead_doctype", "lead"]


def overview(from_date=None, to_date=None, channel=None, queue=None) -> dict:
    start, end = period(from_date, to_date)
    return _cached("overview", [str(start), str(end), channel, queue], lambda: _overview(start, end, channel, queue))


def _overview(start, end, channel, queue) -> dict:
    rows = frappe.get_all(CONV, filters=_filters(start, end, channel, queue), fields=CONV_FIELDS,
                          order_by="creation asc", limit=MAX_ROWS)
    cats = Counter(category(c) for c in rows)
    answered = [c for c in rows if cint(c.ai_replies)]
    first = [_secs(c.handoff_at or c.creation, c.first_agent_reply_at) for c in rows if c.first_agent_reply_at]
    resolve = [_secs(c.creation, c.closed_on) for c in rows if c.closed_on]
    days = {}
    d = start
    while d <= end:
        days[str(d)] = {"ai": 0, "human": 0, "other": 0, "_first": []}
        d = add_days(d, 1)
    for c in rows:
        day = days.get(str(getdate(c.creation)))
        if day is not None:
            day[category(c)] += 1
            if c.first_agent_reply_at:
                day["_first"].append(_secs(c.handoff_at or c.creation, c.first_agent_reply_at))
    fb_filters = _filters(start, end, channel, queue, field="submitted_on")
    feedback = frappe.get_all(FEEDBACK, filters=fb_filters, fields=["rating", "handled_by_assistant"], limit=MAX_ROWS)
    ratings = [cint(f.rating) for f in feedback if cint(f.rating)]
    leads = [c for c in rows if c.get("lead")]
    conversions = 0
    from thinknxg_support.integrations import crm

    for dt in {c.lead_doctype for c in leads if c.lead_doctype}:
        try:
            conversions += crm.converted(dt, list({c.lead for c in leads if c.lead_doctype == dt}))
        except Exception:
            pass
    runs = frappe.get_all("Support Automation Run", filters={"ran_on": _filters(start, end, field="ran_on")["ran_on"]},
                          fields=["rule"], limit=MAX_ROWS) if frappe.db.exists("DocType", "Support Automation Run") else []
    usage = frappe.get_all(USAGE, filters={"creation": _filters(start, end)["creation"]},
                           fields=["kind", "status", "total_tokens"], limit=MAX_ROWS)
    tokens = sum(cint(u.total_tokens) for u in usage)

    def top(values, n=8):
        return [{"label": k, "count": v} for k, v in Counter(x for x in values if x).most_common(n)]

    return {
        "period": {"from": str(start), "to": str(end)},
        "truncated": len(rows) >= MAX_ROWS,
        "totals": {
            "conversations": len(rows),
            "ai_resolved": cats["ai"],
            "human_handled": cats["human"],
            "other": cats["other"],
            "ai_answered": len(answered),
            "ai_resolution_rate": _rate(sum(1 for c in answered if category(c) == "ai"), len(answered)),
            "automation_rate": _rate(cats["ai"], len(rows)),
            "handoffs": sum(1 for c in rows if c.handoff_at),
            "closed": sum(1 for c in rows if c.status == "Closed"),
            "first_response_median": _pct(first, 0.5),
            "first_response_p90": _pct(first, 0.9),
            "resolution_median": _pct(resolve, 0.5),
            "resolution_p90": _pct(resolve, 0.9),
            "csat_average": round(sum(ratings) / len(ratings), 2) if ratings else None,
            "csat_positive": _rate(sum(1 for r in ratings if r >= 4), len(ratings)),
            "ratings": len(ratings),
            "ai_tokens": tokens,
            "ai_calls": len(usage),
            "ai_errors": sum(1 for u in usage if u.status not in ("Success", "Skipped")),
            "leads": len({(c.lead_doctype, c.lead) for c in leads}),
            "lead_conversions": conversions,
            "automation_runs": len(runs),
        },
        "daily": [{"date": k, "ai": v["ai"], "human": v["human"], "other": v["other"],
                   "first_response_median": _pct(v["_first"], 0.5)} for k, v in days.items()],
        "channels": top([c.channel for c in rows]),
        "handoff_reasons": top([c.handoff_reason for c in rows]),
        "intents": top([(c.intent or "").strip().lower() for c in rows]),
        "sentiment": top([c.sentiment for c in rows], 3),
        "languages": top([(c.customer_language or "").lower() for c in rows]),
        "ai_usage": top([u.kind for u in usage], 12),
        "automation": top([r.rule for r in runs], 12),
    }


def agents(from_date=None, to_date=None, channel=None, queue=None) -> list[dict]:
    start, end = period(from_date, to_date)
    return _cached("agents", [str(start), str(end), channel, queue], lambda: _agents(start, end, channel, queue))


def _agents(start, end, channel, queue) -> list[dict]:
    f = _filters(start, end, None, queue, field="assigned_at")
    rows = frappe.get_all(ASSIGN, filters=f, fields=["conversation", "agent", "assigned_at", "first_response_at",
                                                     "ended_at", "outcome"], limit=MAX_ROWS)
    if channel and rows:
        keep = set(frappe.get_all(CONV, filters={"name": ["in", list({r.conversation for r in rows})],
                                                  "channel": channel}, pluck="name"))
        rows = [r for r in rows if r.conversation in keep]
    by = defaultdict(lambda: {"chats": set(), "first": [], "handle": [], "outcomes": Counter()})
    for r in rows:
        if not r.agent:
            continue
        a = by[r.agent]
        a["chats"].add(r.conversation)
        a["first"].append(_secs(r.assigned_at, r.first_response_at))
        a["handle"].append(_secs(r.assigned_at, r.ended_at))
        a["outcomes"][r.outcome or "Open"] += 1
    fb = frappe.get_all(FEEDBACK, filters=_filters(start, end, channel, queue, field="submitted_on"),
                        fields=["agent", "rating"], limit=MAX_ROWS)
    ratings = defaultdict(list)
    for x in fb:
        if x.agent and cint(x.rating):
            ratings[x.agent].append(cint(x.rating))
    acks = defaultdict(list)
    for x in frappe.get_all(ALERT, filters={"alerted_on": _filters(start, end, field="alerted_on")["alerted_on"],
                                            "ack_seconds": [">", 0]}, fields=["user", "ack_seconds"], limit=MAX_ROWS):
        acks[x.user].append(float(x.ack_seconds))
    users = set(by) | set(ratings)
    names = {u.name: u.full_name for u in frappe.get_all("User", filters={"name": ["in", list(users) or [""]]},
                                                       fields=["name", "full_name"])}
    out = []
    for user in users:
        a = by.get(user) or {"chats": set(), "first": [], "handle": [], "outcomes": Counter()}
        r = ratings.get(user, [])
        out.append({"agent": user, "name": names.get(user) or user, "chats": len(a["chats"]),
                    "first_response_median": _pct(a["first"], 0.5), "handling_median": _pct(a["handle"], 0.5),
                    "transferred": a["outcomes"].get("Transferred", 0),
                    "csat_average": round(sum(r) / len(r), 2) if r else None, "ratings": len(r),
                    "alert_ack_median": _pct(acks.get(user, []), 0.5)})
    return sorted(out, key=lambda x: (-x["chats"], x["name"]))


def live() -> dict:
    """Right now (not cached): who is waiting, what is active, visitors on the site, and the latest events."""
    now = now_datetime()
    open_ = {"status": ["!=", "Closed"]}
    waiting = frappe.get_all(CONV, filters={**open_, "handling": "Queued"},
                             fields=["name", "subject", "guest_name", "channel", "queue", "handoff_at", "creation",
                                     "assigned_agent", "urgency", "sentiment"],
                             order_by="handoff_at asc", limit=200)
    for w in waiting:
        w["waiting_seconds"] = _secs(w.handoff_at or w.creation, now)
    active_since = add_to_date(now, minutes=-15)
    active = frappe.get_all(CONV, filters={**open_, "last_activity_at": [">=", active_since]},
                            fields=["handling"], limit=5000)
    visitors = frappe.db.count(CONV, {**open_, "is_guest": 1, "guest_last_seen": [">=", add_to_date(now, seconds=-90)]})
    since = add_to_date(now, hours=-24)
    events = []
    for field, kind in (("creation", "started"), ("handoff_at", "handed over"), ("closed_on", "closed")):
        for c in frappe.get_all(CONV, filters={field: [">=", since]}, fields=["name", "subject", "channel", field],
                                order_by=f"{field} desc", limit=25):
            events.append({"at": str(c.get(field)), "event": kind, "conversation": c.name, "subject": c.subject,
                           "channel": c.channel})
    events.sort(key=lambda e: e["at"], reverse=True)
    return {
        "server_time": str(now),
        "waiting": [{"conversation": w.name, "subject": w.subject, "name": w.guest_name, "channel": w.channel,
                     "queue": w.queue, "waiting_seconds": w.waiting_seconds, "assigned_agent": w.assigned_agent,
                     "urgent": w.urgency == "High", "sentiment": w.sentiment} for w in waiting[:25]],
        "waiting_count": len(waiting),
        "longest_wait_seconds": max((w.waiting_seconds or 0 for w in waiting), default=0),
        "active": dict(Counter(a.handling or "Bot" for a in active)),
        "active_count": len(active),
        "visitors_online": visitors,
        "open_count": frappe.db.count(CONV, open_),
        "events": events[:25],
    }
