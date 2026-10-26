from __future__ import annotations

import frappe
from frappe import _

from thinknxg_support.security import get_portal_user

LANGS = ("en", "ar")
THEMES = ("System", "Light", "Dark")


@frappe.whitelist(methods=["GET"])
def get_profile():
    pu = get_portal_user()
    p = frappe.db.get_value("Support Portal Profile", pu.user,
                            ["default_customer", "language", "time_zone", "theme"], as_dict=True) or {}
    return {"full_name": pu.full_name, "email": pu.email, **p}


@frappe.whitelist(methods=["POST"])
def update_profile(language: str | None = None, time_zone: str | None = None, default_customer: str | None = None,
                   theme: str | None = None):
    pu = get_portal_user()
    if not frappe.db.exists("Support Portal Profile", pu.user):
        frappe.get_doc({"doctype": "Support Portal Profile", "user": pu.user}).insert(ignore_permissions=True)
    doc = frappe.get_doc("Support Portal Profile", pu.user)
    if language is not None:
        if language not in LANGS:
            frappe.throw(_("Unsupported language."))
        doc.language = language
    if theme is not None:
        if theme not in THEMES:
            frappe.throw(_("Unsupported theme."))
        doc.theme = theme
    if time_zone is not None:
        import zoneinfo

        if time_zone and time_zone not in zoneinfo.available_timezones():
            frappe.throw(_("Unknown time zone."))
        doc.time_zone = time_zone
    if default_customer is not None:
        if default_customer and default_customer not in pu.customers:
            frappe.throw(_("You are not authorised for this organisation."), frappe.PermissionError)
        doc.default_customer = default_customer or None
    doc.save(ignore_permissions=True)
    return get_profile()
