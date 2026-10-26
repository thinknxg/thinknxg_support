"""Read-only thinkNXG ERP (ERPNext) views. Field allow-lists prevent leaking costs,
margins, internal remarks or employee data. Writes always go through ERPNext's own
workflows - the portal only raises service requests or tickets about a document.
"""
from __future__ import annotations

from contextlib import contextmanager

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, getdate, nowdate

from thinknxg_support.security import PortalAccessError, PortalUser, log_denied, require_capability
from thinknxg_support.utils import settings

ORDER_FIELDS = ["name", "transaction_date", "delivery_date", "status", "per_delivered", "per_billed",
                "grand_total", "currency", "po_no"]
INVOICE_FIELDS = ["name", "posting_date", "due_date", "status", "grand_total", "outstanding_amount", "currency",
                  "po_no", "is_return"]
ITEM_FIELDS = ["item_code", "item_name", "description", "qty", "uom", "rate", "amount", "delivery_date"]
DOC_CAPABILITY = {"Sales Order": "orders.read", "Sales Invoice": "invoices.read", "Delivery Note": "orders.read"}


def _lookback():
    days = cint(settings().order_lookback_days) or 730
    return add_days(nowdate(), -days)


def assert_document(pu: PortalUser, doctype: str, name: str, customer: str):
    cap = DOC_CAPABILITY.get(doctype)
    if not cap:
        raise PortalAccessError(_("Unsupported document."))
    require_capability(pu, cap, customer)
    row = frappe.db.get_value(doctype, name, ["customer", "docstatus"], as_dict=True) if name else None
    if not row or row.customer != customer or row.docstatus != 1:
        log_denied(pu, doctype if row else None, name, "document ownership mismatch")
        raise PortalAccessError(_("Document not found."))


def list_orders(pu, customer, start=0, page_length=20, status=None):
    require_capability(pu, "orders.read", customer)
    filters = {"customer": customer, "docstatus": 1, "transaction_date": [">=", _lookback()]}
    if status:
        filters["status"] = status
    return frappe.get_all("Sales Order", filters=filters, fields=ORDER_FIELDS, order_by="transaction_date desc",
                          start=cint(start), page_length=min(cint(page_length) or 20, 100))


def get_order(pu, customer, name):
    assert_document(pu, "Sales Order", name, customer)
    doc = frappe.db.get_value("Sales Order", name, ORDER_FIELDS + ["total_taxes_and_charges", "net_total"], as_dict=True)
    doc["items"] = frappe.get_all("Sales Order Item", filters={"parent": name, "parenttype": "Sales Order"},
                                  fields=ITEM_FIELDS, order_by="idx asc")
    doc["deliveries"] = frappe.get_all(
        "Delivery Note",
        filters={"customer": customer, "docstatus": 1,
                 "name": ["in", frappe.get_all("Delivery Note Item", filters={"against_sales_order": name},
                                               pluck="parent", distinct=True) or [""]]},
        fields=["name", "posting_date", "status", "lr_no", "transporter_name"],
    )
    return doc


def list_invoices(pu, customer, start=0, page_length=20, only_outstanding=False):
    require_capability(pu, "invoices.read", customer)
    filters = {"customer": customer, "docstatus": 1, "posting_date": [">=", _lookback()]}
    if cint(only_outstanding):
        filters["outstanding_amount"] = [">", 0]
    return frappe.get_all("Sales Invoice", filters=filters, fields=INVOICE_FIELDS, order_by="posting_date desc",
                          start=cint(start), page_length=min(cint(page_length) or 20, 100))


def get_invoice(pu, customer, name):
    assert_document(pu, "Sales Invoice", name, customer)
    doc = frappe.db.get_value("Sales Invoice", name,
                              INVOICE_FIELDS + ["net_total", "total_taxes_and_charges", "discount_amount"], as_dict=True)
    doc["items"] = frappe.get_all("Sales Invoice Item", filters={"parent": name, "parenttype": "Sales Invoice"},
                                  fields=[f for f in ITEM_FIELDS if f != "delivery_date"], order_by="idx asc")
    doc["taxes"] = frappe.get_all("Sales Taxes and Charges", filters={"parent": name, "parenttype": "Sales Invoice"},
                                  fields=["description", "rate", "tax_amount"], order_by="idx asc")
    return doc


def statement(pu, customer):
    require_capability(pu, "statements.read", customer)
    rows = frappe.get_all("Sales Invoice",
                          filters={"customer": customer, "docstatus": 1, "outstanding_amount": [">", 0]},
                          fields=["currency", "outstanding_amount", "due_date"])
    today = getdate(nowdate())
    totals = {}
    for r in rows:
        t = totals.setdefault(r.currency, {"currency": r.currency, "outstanding": 0.0, "overdue": 0.0, "overdue_count": 0})
        t["outstanding"] += flt(r.outstanding_amount)
        if r.due_date and getdate(r.due_date) < today:
            t["overdue"] += flt(r.outstanding_amount)
            t["overdue_count"] += 1
    payments = frappe.get_all("Payment Entry",
                              filters={"party_type": "Customer", "party": customer, "docstatus": 1,
                                       "payment_type": "Receive"},
                              fields=["name", "posting_date", "paid_amount", "paid_from_account_currency",
                                      "mode_of_payment", "reference_no"],
                              order_by="posting_date desc", limit=10)
    for p in payments:
        p["currency"] = p.pop("paid_from_account_currency", None)
    return {"totals": list(totals.values()), "recent_payments": payments}


@contextmanager
def _elevated():
    """Temporarily run as Administrator for print rendering AFTER authorisation."""
    previous = frappe.session.user
    frappe.set_user("Administrator")
    try:
        yield
    finally:
        frappe.set_user(previous)


def invoice_pdf(pu, customer, name):
    assert_document(pu, "Sales Invoice", name, customer)
    fmt = settings().invoice_print_format or None
    with _elevated():
        pdf = frappe.get_print("Sales Invoice", name, print_format=fmt, as_pdf=True)
    frappe.local.response.filename = f"{name}.pdf"
    frappe.local.response.filecontent = pdf
    frappe.local.response.type = "pdf"


def subscriptions(pu, customer):
    require_capability(pu, "services.request", customer)
    if not settings().show_subscriptions or not frappe.db.exists("DocType", "Subscription"):
        return []
    rows = frappe.get_all("Subscription", filters={"party_type": "Customer", "party": customer},
                          fields=["name", "status", "start_date", "end_date", "current_invoice_end"],
                          order_by="start_date desc", limit=50)
    for r in rows:
        r["plans"] = frappe.get_all("Subscription Plan Detail", filters={"parent": r.name}, fields=["plan", "qty"])
    return rows


def customer_profile(pu, customer):
    c = frappe.db.get_value("Customer", customer,
                            ["name", "customer_name", "customer_group", "territory", "default_currency"], as_dict=True)
    if not c or customer not in pu.customers:
        raise PortalAccessError(_("Organisation not found."))
    return c
