from __future__ import annotations

import frappe
from frappe import _

from thinknxg_support import ratelimit
from thinknxg_support.api.v1._base import context
from thinknxg_support.integrations import erpnext, helpdesk
from thinknxg_support.security import PortalAccessError, log_denied
from thinknxg_support.utils import clean_html, clean_text, require_module, settings

REQUEST_FIELDS = ["name", "subject", "service", "status", "priority", "helpdesk_ticket", "reference_doctype",
                  "reference_name", "creation", "modified", "raised_by"]


def _ctx(organization, capability="services.request"):
    require_module("services")
    return context(organization, capability)


@frappe.whitelist(methods=["GET"])
def catalogue(organization=None):
    pu, customer = _ctx(organization)
    out = []
    for name in frappe.get_all("Support Service", filters={"enabled": 1}, pluck="name",
                               order_by="sort_order asc, service_name asc"):
        svc = frappe.get_cached_doc("Support Service", name)
        if not svc.is_eligible(customer) or not pu.can(svc.required_capability or "services.request", customer):
            continue
        out.append({"name": svc.name, "category": svc.category, "description": svc.description,
                    "response_target": svc.response_target, "instructions": svc.instructions,
                    "handling": svc.handling})
    return out


@frappe.whitelist(methods=["POST"])
def create_request(service, subject, details, organization=None, priority="Medium",
                   reference_doctype=None, reference_name=None):
    pu, customer = _ctx(organization)
    ratelimit.check("ticket", settings().ticket_rate_limit)
    if not frappe.db.exists("Support Service", service):
        raise PortalAccessError(_("Service not found."))
    svc = frappe.get_cached_doc("Support Service", service)
    if not svc.is_eligible(customer) or not pu.can(svc.required_capability or "services.request", customer):
        log_denied(pu, "Support Service", service, "service not eligible")
        raise PortalAccessError(_("This service is not available for your organisation."))
    if reference_doctype or reference_name:
        erpnext.assert_document(pu, reference_doctype, reference_name, customer)
    if priority not in ("Low", "Medium", "High", "Urgent"):
        priority = "Medium"
    subject = clean_text(subject, 140)
    if len(subject) < 3:
        frappe.throw(_("Please enter a subject."))

    req = frappe.get_doc({
        "doctype": "Support Request",
        "subject": subject,
        "service": service,
        "customer": customer,
        "raised_by": pu.user,
        "priority": priority,
        "details": clean_html(details),
        "reference_doctype": reference_doctype or None,
        "reference_name": reference_name or None,
    })
    req.insert(ignore_permissions=True)

    if svc.handling == "Helpdesk Ticket" and helpdesk.available():
        ref = f"<p>{_('Related document')}: {reference_doctype} {reference_name}</p>" if reference_name else ""
        ticket = helpdesk.create_ticket(
            subject=f"[{svc.name}] {subject}",
            description=f"{req.details or ''}{ref}<p>{_('Portal request')} {req.name}</p>",
            raised_by=pu.email, customer=customer, contact=pu.contacts[0] if pu.contacts else None,
            ticket_type=svc.ticket_type, priority=svc.priority, agent_group=svc.agent_group, via="service",
        )
        req.db_set({"helpdesk_ticket": ticket, "status": "Escalated"})
    return {"name": req.name, "helpdesk_ticket": req.helpdesk_ticket}


def _request_visible(pu, row, customer) -> bool:
    if row.customer != customer:
        return False
    return row.raised_by == pu.user or pu.can("services.organization", customer)


@frappe.whitelist(methods=["GET"])
def my_requests(organization=None, scope="own"):
    pu, customer = _ctx(organization)
    filters = {"customer": customer}
    if scope != "organization" or not pu.can("services.organization", customer):
        filters["raised_by"] = pu.user
    return frappe.get_all("Support Request", filters=filters, fields=REQUEST_FIELDS, order_by="modified desc",
                          limit=200)


@frappe.whitelist(methods=["GET"])
def get_request(name, organization=None):
    pu, customer = _ctx(organization)
    row = frappe.db.get_value("Support Request", name, REQUEST_FIELDS + ["customer", "details", "customer_response"],
                              as_dict=True) if name else None
    if not row or not _request_visible(pu, row, customer):
        log_denied(pu, None, name, "request access denied")
        raise PortalAccessError(_("Request not found."))
    row.pop("customer", None)
    return row


@frappe.whitelist(methods=["GET"])
def subscriptions(organization=None):
    pu, customer = _ctx(organization)
    return erpnext.subscriptions(pu, customer)
