import frappe

try:
    from frappe.tests import IntegrationTestCase as BaseTestCase  # v16
except ImportError:  # pragma: no cover
    from frappe.tests.utils import FrappeTestCase as BaseTestCase  # noqa: F401

from thinknxg_support.utils import clear_request_cache


def _tree_leaf(doctype, root, parent_field, name_field, leaf):
    """A fresh site (setup wizard not run) has no Customer Group / Territory tree yet."""
    found = frappe.db.get_value(doctype, {"is_group": 0})
    if found:
        return found
    if not frappe.db.exists(doctype, root):
        frappe.get_doc({"doctype": doctype, name_field: root, "is_group": 1}).insert(ignore_permissions=True)
    if not frappe.db.exists(doctype, leaf):
        frappe.get_doc({"doctype": doctype, name_field: leaf, "is_group": 0, parent_field: root}).insert(ignore_permissions=True)
    return leaf


def make_customer(name):
    if frappe.db.exists("Customer", name):
        return name
    group = _tree_leaf("Customer Group", "All Customer Groups", "parent_customer_group", "customer_group_name", "Commercial")
    territory = _tree_leaf("Territory", "All Territories", "parent_territory", "territory_name", "Test Territory")
    doc = frappe.get_doc({
        "doctype": "Customer",
        "customer_name": name,
        "customer_type": "Company",
        "customer_group": group,
        "territory": territory,
    }).insert(ignore_permissions=True)
    return doc.name


def make_user(email, first_name):
    if not frappe.db.exists("User", email):
        frappe.get_doc({
            "doctype": "User", "email": email, "first_name": first_name, "user_type": "Website User",
            "send_welcome_email": 0,
        }).insert(ignore_permissions=True)
    return email


def make_contact(email, customers):
    name = frappe.db.get_value("Contact", {"user": email})
    if name:
        doc = frappe.get_doc("Contact", name)
    else:
        doc = frappe.get_doc({"doctype": "Contact", "first_name": email.split("@")[0], "user": email,
                              "email_ids": [{"email_id": email, "is_primary": 1}]})
    linked = {l.link_name for l in doc.links}
    for c in customers:
        if c not in linked:
            doc.append("links", {"link_doctype": "Customer", "link_name": c})
    doc.save(ignore_permissions=True) if not doc.is_new() else doc.insert(ignore_permissions=True)
    return doc.name


def grant(user, customer, level="Self", enabled=1, **kw):
    existing = frappe.db.get_value("Support Organization Access",
                                   {"user": user, "customer": customer, "access_level": level})
    if existing:
        frappe.delete_doc("Support Organization Access", existing, force=True, ignore_permissions=True)
    doc = frappe.get_doc({"doctype": "Support Organization Access", "user": user, "customer": customer,
                          "access_level": level, "enabled": enabled, **kw})
    doc.insert(ignore_permissions=True)
    return doc.name


def as_user(user):
    frappe.set_user(user)
    clear_request_cache()
