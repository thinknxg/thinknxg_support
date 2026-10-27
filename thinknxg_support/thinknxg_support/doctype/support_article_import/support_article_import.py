# Copyright (c) 2026, Kreatao and contributors
import frappe
from frappe.model.document import Document


class SupportArticleImport(Document):
    pass


def _mgr():
    frappe.only_for(["System Manager", "Support Portal Administrator", "Support Manager"])


@frappe.whitelist(methods=["POST"])
def publish(names):
    _mgr()
    from thinknxg_support.integrations.kb_import import importer

    names = frappe.parse_json(names) if isinstance(names, str) and names.startswith("[") else (
        [names] if isinstance(names, str) else names)
    return importer.publish_many(names)


@frappe.whitelist(methods=["POST"])
def reject(names):
    _mgr()
    names = frappe.parse_json(names) if isinstance(names, str) and names.startswith("[") else (
        [names] if isinstance(names, str) else names)
    for n in names:
        if frappe.db.get_value("Support Article Import", n, "status") != "Published":
            frappe.db.set_value("Support Article Import", n, "status", "Rejected")
    return len(names)


@frappe.whitelist(methods=["GET"])
def preview(name):
    _mgr()
    from thinknxg_support.integrations.kb_import import importer

    return importer.preview(name)
