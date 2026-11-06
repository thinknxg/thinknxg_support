"""Customer satisfaction per agent (and per week or month): chats closed, surveys answered, average rating, CSAT
(share of 4-5 star ratings), resolution answers and the star distribution."""
import frappe
from frappe import _
from frappe.utils import getdate


def _period(d, how):
    d = getdate(d)
    if how == "Agent and Week":
        y, w, _x = d.isocalendar()
        return f"{y}-W{w:02d}"
    if how == "Agent and Month":
        return d.strftime("%Y-%m")
    return None


def execute(filters=None):
    f = frappe._dict(filters or {})
    how = f.period or "Agent"
    rng = ["between", [f.from_date + " 00:00:00", f.to_date + " 23:59:59"]]
    cond = {"submitted_on": rng}
    if f.agent:
        cond["agent"] = f.agent
    if f.queue:
        cond["queue"] = f.queue
    rows = frappe.get_all("Support Chat Feedback", filters=cond,
                          fields=["agent", "rating", "resolved", "sentiment", "submitted_on"], limit=500000)
    ccond = {"channel": ["in", ["Live Chat", "WhatsApp"]], "status": "Closed", "resolved_at": rng}
    if f.agent:
        ccond["assigned_agent"] = f.agent
    if f.queue:
        ccond["queue"] = f.queue
    chats = frappe.get_all("Support Conversation Link", filters=ccond, fields=["assigned_agent", "resolved_at"], limit=500000)

    agg = {}

    def bucket(agent, when):
        key = (agent or "", _period(when, how))
        return agg.setdefault(key, {"agent": agent or None, "agent_name": frappe.utils.get_fullname(agent) if agent else _("Assistant only"),
                                    "period": key[1], "chats": 0, "surveys": 0, "_sum": 0, "_happy": 0, "yes": 0,
                                    "partially": 0, "no": 0, "positive": 0, "negative": 0,
                                    "s5": 0, "s4": 0, "s3": 0, "s2": 0, "s1": 0})

    for c in chats:
        bucket(c.assigned_agent, c.resolved_at)["chats"] += 1
    for r in rows:
        b = bucket(r.agent, r.submitted_on)
        b["surveys"] += 1
        b["_sum"] += r.rating or 0
        b["_happy"] += 1 if (r.rating or 0) >= 4 else 0
        b[f"s{min(5, max(1, r.rating or 1))}"] += 1
        if r.resolved:
            b[r.resolved.lower()] += 1
        if r.sentiment == "Positive":
            b["positive"] += 1
        elif r.sentiment == "Negative":
            b["negative"] += 1
    data = []
    for b in sorted(agg.values(), key=lambda x: (x["agent_name"] or "", x["period"] or "")):
        n = b["surveys"]
        b["avg_rating"] = round(b.pop("_sum") / n, 2) if n else None
        b["csat"] = round(100.0 * b.pop("_happy") / n, 1) if n else None
        b["response_rate"] = round(100.0 * n / b["chats"], 1) if b["chats"] else None
        b["resolved_pct"] = round(100.0 * b["yes"] / n, 1) if n else None
        data.append(b)

    columns = [
        {"fieldname": "agent", "label": _("Agent"), "fieldtype": "Link", "options": "User", "width": 190},
        {"fieldname": "agent_name", "label": _("Name"), "fieldtype": "Data", "width": 150},
    ]
    if how != "Agent":
        columns.append({"fieldname": "period", "label": _("Week") if how == "Agent and Week" else _("Month"),
                        "fieldtype": "Data", "width": 90})
    columns += [
        {"fieldname": "chats", "label": _("Chats Closed"), "fieldtype": "Int", "width": 100},
        {"fieldname": "surveys", "label": _("Feedback"), "fieldtype": "Int", "width": 80},
        {"fieldname": "response_rate", "label": _("Response %"), "fieldtype": "Percent", "width": 95},
        {"fieldname": "avg_rating", "label": _("Avg Rating"), "fieldtype": "Float", "precision": 2, "width": 90},
        {"fieldname": "csat", "label": _("CSAT %"), "fieldtype": "Percent", "width": 80,
         "description": _("Share of 4 and 5 star ratings")},
        {"fieldname": "resolved_pct", "label": _("Resolved %"), "fieldtype": "Percent", "width": 90},
        {"fieldname": "yes", "label": _("Resolved"), "fieldtype": "Int", "width": 80},
        {"fieldname": "partially", "label": _("Partially"), "fieldtype": "Int", "width": 80},
        {"fieldname": "no", "label": _("Not Resolved"), "fieldtype": "Int", "width": 100},
        {"fieldname": "positive", "label": _("Positive"), "fieldtype": "Int", "width": 75},
        {"fieldname": "negative", "label": _("Negative"), "fieldtype": "Int", "width": 80},
    ] + [{"fieldname": f"s{i}", "label": "★" * i, "fieldtype": "Int", "width": 70} for i in (5, 4, 3, 2, 1)]
    agents = [d for d in data if d["avg_rating"] is not None]
    chart = None
    if agents and how == "Agent":
        chart = {"data": {"labels": [d["agent_name"] for d in agents],
                          "datasets": [{"name": _("Avg Rating"), "values": [d["avg_rating"] for d in agents]}]},
                 "type": "bar", "colors": ["#ca8a04"], "axisOptions": {"yAxisMode": "tick"}}
    return columns, data, None, chart
