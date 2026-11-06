"""Per agent and activity: alerts received, acknowledged by the agent, picked up by someone, missed, and how fast."""
import frappe
from frappe import _


def execute(filters=None):
    f = frappe._dict(filters or {})
    cond = {"alerted_on": ["between", [f.from_date + " 00:00:00", f.to_date + " 23:59:59"]]}
    if f.user:
        cond["user"] = f.user
    if f.kind:
        cond["kind"] = f.kind
    rows = frappe.get_all("Support Agent Alert", filters=cond, fields=["user", "kind", "status", "ack_seconds"], limit=200000)
    agg = {}
    for r in rows:
        a = agg.setdefault((r.user, r.kind), {"user": r.user, "kind": r.kind, "alerts": 0, "acknowledged": 0, "handled": 0,
                                              "missed": 0, "open": 0, "_secs": []})
        a["alerts"] += 1
        if r.status == "Acknowledged":
            a["acknowledged"] += 1
            a["_secs"].append(r.ack_seconds or 0)
        elif r.status == "Handled":
            a["handled"] += 1
        elif r.status == "Expired":
            a["missed"] += 1
        else:
            a["open"] += 1
    data = []
    for a in sorted(agg.values(), key=lambda x: (x["user"], x["kind"])):
        secs = sorted(a.pop("_secs"))
        a["avg_seconds"] = round(sum(secs) / len(secs), 1) if secs else None
        a["median_seconds"] = secs[len(secs) // 2] if secs else None
        a["max_seconds"] = max(secs) if secs else None
        data.append(a)
    columns = [
        {"fieldname": "user", "label": _("Agent"), "fieldtype": "Link", "options": "User", "width": 200},
        {"fieldname": "kind", "label": _("Activity"), "fieldtype": "Data", "width": 150},
        {"fieldname": "alerts", "label": _("Alerts"), "fieldtype": "Int", "width": 80},
        {"fieldname": "acknowledged", "label": _("Acknowledged"), "fieldtype": "Int", "width": 110},
        {"fieldname": "handled", "label": _("Picked Up"), "fieldtype": "Int", "width": 90,
         "description": _("Stopped because the work was assigned or answered")},
        {"fieldname": "missed", "label": _("Missed"), "fieldtype": "Int", "width": 80},
        {"fieldname": "open", "label": _("Open"), "fieldtype": "Int", "width": 70},
        {"fieldname": "avg_seconds", "label": _("Avg Seconds"), "fieldtype": "Float", "width": 100},
        {"fieldname": "median_seconds", "label": _("Median Seconds"), "fieldtype": "Float", "width": 120},
        {"fieldname": "max_seconds", "label": _("Max Seconds"), "fieldtype": "Float", "width": 100},
    ]
    return columns, data
