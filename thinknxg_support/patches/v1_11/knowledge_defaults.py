"""1.11: store the new knowledge and language settings' defaults where nothing is set yet."""
import frappe

DEFAULTS = {"index_documents": 1, "index_websites": 1, "knowledge_language": "en", "translate_questions": 1,
            "answer_language": "Customer's language", "localize_messages": 1}


def execute():
    singles = frappe.qb.DocType("Singles")
    have = {r[0] for r in frappe.qb.from_(singles).select(singles.field)
            .where(singles.doctype == "Support AI Settings").run()}
    for field, value in DEFAULTS.items():
        if field not in have:
            frappe.db.set_single_value("Support AI Settings", field, value)
