from __future__ import annotations

import frappe
from frappe import _

from thinknxg_support import ratelimit
from thinknxg_support.api.v1._base import context
from thinknxg_support.integrations import erpnext
from thinknxg_support.utils import require_module


def _ctx(organization):
    require_module("account")
    return context(organization)


@frappe.whitelist(methods=["GET"])
def customer_profile(organization=None):
    pu, customer = _ctx(organization)
    data = erpnext.customer_profile(pu, customer)
    data["access_levels"] = sorted(pu.levels_for(customer))
    return data


@frappe.whitelist(methods=["GET"])
def orders(organization=None, start=0, page_length=20, status=None):
    pu, customer = _ctx(organization)
    return erpnext.list_orders(pu, customer, start, page_length, status)


@frappe.whitelist(methods=["GET"])
def order(name, organization=None):
    pu, customer = _ctx(organization)
    return erpnext.get_order(pu, customer, name)


@frappe.whitelist(methods=["GET"])
def invoices(organization=None, start=0, page_length=20, only_outstanding=0):
    pu, customer = _ctx(organization)
    return erpnext.list_invoices(pu, customer, start, page_length, only_outstanding)


@frappe.whitelist(methods=["GET"])
def invoice(name, organization=None):
    pu, customer = _ctx(organization)
    return erpnext.get_invoice(pu, customer, name)


@frappe.whitelist(methods=["GET"])
def invoice_pdf(name, organization=None):
    pu, customer = _ctx(organization)
    ratelimit.check("download", 30)
    erpnext.invoice_pdf(pu, customer, name)


@frappe.whitelist(methods=["GET"])
def statement(organization=None):
    pu, customer = _ctx(organization)
    return erpnext.statement(pu, customer)


@frappe.whitelist(methods=["GET"])
def members(organization=None):
    pu, customer = context(organization, "members.read")
    rows = frappe.get_all("Support Organization Access",
                          filters={"customer": customer},
                          fields=["user", "access_level", "enabled", "valid_until"], order_by="user asc")
    for r in rows:
        r["full_name"] = frappe.db.get_value("User", r.user, "full_name")
    return rows


@frappe.whitelist(methods=["POST"])
def request_member(email, full_name, access_level="Self", organization=None, note=None):
    """Organization Managers can REQUEST access for a colleague; an administrator approves it."""
    pu, customer = context(organization, "members.request")
    ratelimit.check("ticket", 5)
    from frappe.utils import validate_email_address

    email = validate_email_address(email, throw=True)
    if access_level not in ("Self", "Billing", "Service"):
        frappe.throw(_("Organization Manager access can only be granted by an administrator."))
    req = frappe.get_doc({
        "doctype": "Support Request",
        "subject": _("Portal access request: {0}").format(email),
        "customer": customer,
        "raised_by": pu.user,
        "priority": "Medium",
        "details": "<p>{0}</p><ul><li>{1}: {2}</li><li>{3}: {4}</li><li>{5}: {6}</li></ul>".format(
            _("Please grant portal access"), _("Name"), frappe.utils.escape_html(full_name or ""),
            _("Email"), frappe.utils.escape_html(email), _("Access level"), access_level)
        + (f"<p>{frappe.utils.escape_html(note)}</p>" if note else ""),
    })
    req.insert(ignore_permissions=True)
    return {"request": req.name}
