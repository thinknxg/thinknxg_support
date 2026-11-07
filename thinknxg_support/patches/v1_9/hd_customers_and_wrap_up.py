"""1.9: register existing support customers as HD Customers (with their contacts); End chat always asks whether
the issue was resolved and whether a follow-up is needed; apps check alerts every 5 seconds."""
import frappe


def execute():
    from thinknxg_support.install import ensure_resolution_questions

    ps = frappe.get_single("Support Portal Settings")
    if ps.meta.has_field("wrap_up_questions") and ensure_resolution_questions(ps):
        ps.flags.ignore_permissions = True
        ps.flags.ignore_validate = True
        ps.save()
    if frappe.db.exists("DocType", "Support Agent App Settings"):
        if (frappe.db.get_single_value("Support Agent App Settings", "alerts_poll_seconds") or 15) == 15:
            frappe.db.set_single_value("Support Agent App Settings", "alerts_poll_seconds", 5)
    if not frappe.db.exists("DocType", "HD Customer") or not frappe.db.exists("DocType", "Customer"):
        return
    from thinknxg_support.integrations import helpdesk

    customers = set(frappe.get_all("Support Conversation Link", filters={"customer": ["is", "set"]}, pluck="customer",
                                   distinct=True))
    customers |= set(frappe.db.sql_list("""select distinct dl.link_name from `tabDynamic Link` dl
        join `tabContact` c on c.name = dl.parent
        where dl.parenttype = 'Contact' and dl.link_doctype = 'Customer' and ifnull(c.user, '') != ''"""))
    for customer in sorted(customers):
        if frappe.db.get_value("Customer", customer, "disabled") == 0:
            try:
                helpdesk.sync_hd_customer(customer)
            except Exception:
                frappe.log_error(title=f"thinkNXG Support: HD Customer backfill failed for {customer}")
