import frappe
from frappe.utils import add_days, cint, nowdate


def purge_usage_logs():
    days = cint(frappe.db.get_single_value("Support AI Settings", "usage_retention_days")) or 90
    frappe.db.delete("Support AI Usage Log", {"creation": ["<", add_days(nowdate(), -days)]})
