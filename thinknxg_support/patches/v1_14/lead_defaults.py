"""1.14: store the new lead settings' defaults where nothing is set yet."""
import frappe


def execute():
    singles = frappe.qb.DocType("Singles")
    have = {r[0] for r in frappe.qb.from_(singles).select(singles.field)
            .where(singles.doctype == "Support Portal Settings").run()}
    for field, value in {"lead_target": "Automatic", "lead_source": "Live Chat"}.items():
        if field not in have:
            frappe.db.set_single_value("Support Portal Settings", field, value)
