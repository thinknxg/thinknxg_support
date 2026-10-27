"""Daily chat volume, automation share, handoffs, response times, AI latency, tokens and feedback."""
import frappe
from frappe import _
from frappe.utils import add_days, getdate, time_diff_in_seconds


def execute(filters=None):
    f = frappe._dict(filters or {})
    start, end = getdate(f.from_date), getdate(f.to_date)
    cond = {"creation": ["between", [start, add_days(end, 1)]]}
    if f.channel:
        cond["channel"] = f.channel
    convs = frappe.get_all("Support Conversation Link", filters=cond,
                           fields=["name", "creation", "handoff_at", "first_agent_reply_at", "resolved_by_assistant",
                                   "chat_rating", "ai_replies"], limit=100000)
    usage = frappe.get_all("Support AI Usage Log", filters={"creation": ["between", [start, add_days(end, 1)]],
                                                            "kind": "Answer"},
                           fields=["creation", "status", "latency_ms", "first_token_ms", "total_tokens"], limit=100000)
    names = [c.name for c in convs]
    fb = frappe.get_all("Support Portal Message", filters={"conversation": ["in", names or [""]], "feedback": ["is", "set"]},
                        fields=["creation", "feedback"], limit=100000)
    days = {}

    def day(d):
        k = getdate(d)
        return days.setdefault(k, {"date": k, "conversations": 0, "assistant_only": 0, "handoffs": 0, "_wait": [],
                                   "ai_answers": 0, "ai_errors": 0, "_ft": [], "tokens": 0, "_fb": [0, 0], "_rate": []})

    for c in convs:
        d = day(c.creation)
        d["conversations"] += 1
        d["assistant_only"] += 1 if c.resolved_by_assistant else 0
        if c.handoff_at:
            d["handoffs"] += 1
            if c.first_agent_reply_at:
                d["_wait"].append(time_diff_in_seconds(c.first_agent_reply_at, c.handoff_at))
        if c.chat_rating:
            d["_rate"].append(c.chat_rating * 5)
    for u in usage:
        d = day(u.creation)
        if u.status == "Success":
            d["ai_answers"] += 1
            d["_ft"].append(u.first_token_ms or 0)
        elif u.status in ("Error", "Timeout"):
            d["ai_errors"] += 1
        d["tokens"] += u.total_tokens or 0
    for m in fb:
        d = day(m.creation)
        d["_fb"][0 if m.feedback == "Helpful" else 1] += 1

    def p95(xs):
        xs = sorted(xs)
        return xs[min(len(xs) - 1, int(0.95 * len(xs)))] if xs else None

    data = []
    for k in sorted(days):
        d = days[k]
        data.append({
            "date": d["date"], "conversations": d["conversations"], "assistant_only": d["assistant_only"],
            "handoffs": d["handoffs"],
            "median_wait_min": round(sorted(d["_wait"])[len(d["_wait"]) // 2] / 60, 1) if d["_wait"] else None,
            "ai_answers": d["ai_answers"], "ai_errors": d["ai_errors"], "p95_first_token_ms": p95(d["_ft"]),
            "tokens": d["tokens"],
            "helpful_pct": round(100 * d["_fb"][0] / sum(d["_fb"]), 0) if sum(d["_fb"]) else None,
            "avg_rating": round(sum(d["_rate"]) / len(d["_rate"]), 1) if d["_rate"] else None,
        })
    columns = [
        {"fieldname": "date", "label": _("Date"), "fieldtype": "Date", "width": 110},
        {"fieldname": "conversations", "label": _("Conversations"), "fieldtype": "Int", "width": 120},
        {"fieldname": "assistant_only", "label": _("Solved by Assistant"), "fieldtype": "Int", "width": 140},
        {"fieldname": "handoffs", "label": _("Handed to Agents"), "fieldtype": "Int", "width": 130},
        {"fieldname": "median_wait_min", "label": _("Median Wait for Agent (min)"), "fieldtype": "Float", "width": 180},
        {"fieldname": "ai_answers", "label": _("AI Answers"), "fieldtype": "Int", "width": 100},
        {"fieldname": "ai_errors", "label": _("AI Errors"), "fieldtype": "Int", "width": 90},
        {"fieldname": "p95_first_token_ms", "label": _("P95 First Token (ms)"), "fieldtype": "Int", "width": 150},
        {"fieldname": "tokens", "label": _("Tokens"), "fieldtype": "Int", "width": 100},
        {"fieldname": "helpful_pct", "label": _("Helpful %"), "fieldtype": "Percent", "width": 100},
        {"fieldname": "avg_rating", "label": _("Avg Rating (of 5)"), "fieldtype": "Float", "width": 130},
    ]
    chart = {"data": {"labels": [str(r["date"]) for r in data],
                      "datasets": [{"name": _("Conversations"), "values": [r["conversations"] for r in data]},
                                   {"name": _("Solved by Assistant"), "values": [r["assistant_only"] for r in data]},
                                   {"name": _("Handed to Agents"), "values": [r["handoffs"] for r in data]}]},
             "type": "line"}
    return columns, data, None, chart
