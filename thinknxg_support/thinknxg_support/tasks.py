import frappe
from frappe.utils import add_days, cint, nowdate


def expire_access_and_grants():
    today = nowdate()
    expired = frappe.get_all(
        "Support Organization Access",
        filters={"enabled": 1, "valid_until": ["<", today]},
        pluck="name",
    )
    for name in expired:
        frappe.db.set_value("Support Organization Access", name, "enabled", 0)
    grants = frappe.get_all(
        "Support Download Grant", filters={"enabled": 1, "valid_until": ["<", today]}, pluck="name"
    )
    for name in grants:
        frappe.db.set_value("Support Download Grant", name, "enabled", 0)
    if expired or grants:
        from thinknxg_support.audit import log_event

        log_event("Administrative Change", details={"expired_access": len(expired), "expired_grants": len(grants)},
                  user="Administrator")


def purge_old_events():
    days = cint(frappe.db.get_single_value("Support Portal Settings", "event_retention_days")) or 365
    cutoff = add_days(nowdate(), -days)
    frappe.db.delete("Support Portal Event", {"creation": ["<", cutoff]})


def retry_failed_deliveries():
    from thinknxg_support.integrations import raven

    raven.retry_failed()
