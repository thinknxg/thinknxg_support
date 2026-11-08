"""1.14: store the new chat-message and agent-status settings' defaults where nothing is set yet. Nobody gets a
status or a shift: routing stays as it was until people use them."""
import frappe

DEFAULTS = {"allow_customer_edits": 1, "customer_edit_minutes": 5, "allow_reactions": 1, "allow_guest_uploads": 0,
            "allow_voice_notes": 1, "max_voice_seconds": 120, "auto_away_minutes": 10}


def execute():
    singles = frappe.qb.DocType("Singles")
    have = {r[0] for r in frappe.qb.from_(singles).select(singles.field)
            .where(singles.doctype == "Support Portal Settings").run()}
    for field, value in DEFAULTS.items():
        if field not in have:
            frappe.db.set_single_value("Support Portal Settings", field, value)
