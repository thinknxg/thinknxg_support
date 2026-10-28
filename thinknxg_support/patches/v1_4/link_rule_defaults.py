"""1.4.2: website and e-mail rules on sources that have none (docs.frappe.io/erpnext -> docs.thinknxg.com)."""
import frappe


def execute():
    from thinknxg_support.integrations.kb_import.rebrand import DEFAULT_LINK_RULES

    if not frappe.db.exists("DocType", "Support Knowledge Source"):
        return
    for name in frappe.get_all("Support Knowledge Source", pluck="name"):
        doc = frappe.get_doc("Support Knowledge Source", name)
        if doc.get("link_rules"):
            continue
        for kind, find, repl, keep, enabled in DEFAULT_LINK_RULES:
            doc.append("link_rules", {"kind": kind, "find": find, "replace_with": repl, "keep_path": keep, "enabled": enabled})
        doc.flags.ignore_validate = True
        doc.save(ignore_permissions=True)
