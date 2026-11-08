"""1.10: store the new AI settings' defaults on existing sites (a Single's defaults are not stored until it is
saved) and add the "Frustrated Customer" alert rule. Values someone already set are left alone."""
import frappe

DEFAULTS = {"tone": "Friendly", "history_turns": 8, "enable_copilot": 1, "analyze_messages": 0,
            "summary_on_handoff": 1, "alert_on_negative": 1}


def execute():
    from thinknxg_support.install import ensure_agent_tool_defaults

    singles = frappe.qb.DocType("Singles")
    have = {r[0] for r in frappe.qb.from_(singles).select(singles.field)
            .where(singles.doctype == "Support AI Settings").run()}
    for field, value in DEFAULTS.items():
        if field not in have:
            frappe.db.set_single_value("Support AI Settings", field, value)
    ensure_agent_tool_defaults()
