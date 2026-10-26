from __future__ import annotations

import json

import frappe
from frappe.utils import cint

from thinknxg_support.integrations.notifications import DEFAULT_PREFS, PORTAL_DOCTYPES, prefs
from thinknxg_support.security import get_portal_user


@frappe.whitelist(methods=["GET"])
def list_notifications(limit=30):
    pu = get_portal_user()
    rows = frappe.get_all("Notification Log",
                          filters={"for_user": pu.user, "document_type": ["in", PORTAL_DOCTYPES]},
                          fields=["name", "subject", "document_type", "document_name", "read", "creation"],
                          order_by="creation desc", limit=min(cint(limit) or 30, 100))
    for r in rows:
        r["subject"] = frappe.utils.strip_html(r.subject or "")
    unread = frappe.db.count("Notification Log", {"for_user": pu.user, "read": 0,
                                                  "document_type": ["in", PORTAL_DOCTYPES]})
    return {"items": rows, "unread": unread}


@frappe.whitelist(methods=["POST"])
def mark_read(names=None, all=0):
    pu = get_portal_user()
    filters = {"for_user": pu.user, "read": 0}
    if not cint(all):
        names = json.loads(names) if isinstance(names, str) else (names or [])
        if not names:
            return {"ok": True}
        filters["name"] = ["in", [str(n) for n in names][:200]]
    for name in frappe.get_all("Notification Log", filters=filters, pluck="name", limit=500):
        frappe.db.set_value("Notification Log", name, "read", 1, update_modified=False)
    return {"ok": True}


@frappe.whitelist(methods=["GET"])
def get_preferences():
    pu = get_portal_user()
    return prefs(pu.user)


@frappe.whitelist(methods=["POST"])
def update_preferences(**kwargs):
    pu = get_portal_user()
    if frappe.db.exists("Support Notification Preference", pu.user):
        doc = frappe.get_doc("Support Notification Preference", pu.user)
    else:
        doc = frappe.new_doc("Support Notification Preference")
        doc.user = pu.user
    for key in DEFAULT_PREFS:
        if key in kwargs:
            doc.set(key, 1 if cint(kwargs[key]) else 0)
    doc.save(ignore_permissions=True)
    return prefs(pu.user)
