from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint

from thinknxg_support import ratelimit
from thinknxg_support.api.v1._base import context
from thinknxg_support.integrations import helpdesk
from thinknxg_support.security import PortalAccessError, log_denied
from thinknxg_support.utils import clean_text, require_module, save_private_file, settings, stream_file, uploaded_files


def _ctx(organization):
    require_module("tickets")
    pu, customer = context(organization, "tickets.own")
    helpdesk.require()
    return pu, customer


@frappe.whitelist(methods=["GET"])
def list_tickets(organization=None, scope="own", status=None, search=None, start=0, page_length=20):
    pu, customer = _ctx(organization)
    if scope not in ("own", "organization"):
        scope = "own"
    return helpdesk.list_tickets(pu, customer, scope=scope, status=status, search=search,
                                 start=start, page_length=page_length)


@frappe.whitelist(methods=["GET"])
def get_ticket(ticket, organization=None):
    pu, customer = _ctx(organization)
    return helpdesk.get_ticket(pu, ticket, customer)


@frappe.whitelist(methods=["GET"])
def options(organization=None):
    _ctx(organization)
    return {"ticket_types": helpdesk.ticket_types(), "priorities": helpdesk.priorities()}


@frappe.whitelist(methods=["POST"])
def create_ticket(subject, description, organization=None, ticket_type=None, priority=None):
    pu, customer = _ctx(organization)
    ratelimit.check("ticket", settings().ticket_rate_limit)
    subject = clean_text(subject, 140)
    if len(subject) < 3:
        frappe.throw(_("Please enter a subject."))
    files = uploaded_files()
    ticket = helpdesk.create_ticket(
        subject=subject,
        description=description,
        raised_by=pu.email,
        customer=customer,
        contact=pu.contacts[0] if pu.contacts else None,
        ticket_type=clean_text(ticket_type, 140) or None,
        priority=clean_text(priority, 140) or None,
    )
    for fname, data in files:
        save_private_file(fname, data, "HD Ticket", ticket)
    return {"ticket": ticket}


@frappe.whitelist(methods=["POST"])
def reply(ticket, message, organization=None):
    pu, customer = _ctx(organization)
    ratelimit.check("message", settings().message_rate_limit)
    helpdesk.assert_ticket_access(pu, ticket, customer)
    file_names = []
    for fname, data in uploaded_files():
        file_names.append(save_private_file(fname, data, "HD Ticket", ticket)["name"])
    helpdesk.add_reply(pu, ticket, customer, message, file_names)
    return helpdesk.get_ticket(pu, ticket, customer)


@frappe.whitelist(methods=["POST"])
def rate(ticket, stars, comment=None, organization=None):
    pu, customer = _ctx(organization)
    helpdesk.rate(pu, ticket, customer, cint(stars), comment)
    return {"ok": True}


@frappe.whitelist(methods=["POST"])
def reopen(ticket, organization=None):
    pu, customer = _ctx(organization)
    helpdesk.reopen(pu, ticket, customer)
    return {"ok": True}


@frappe.whitelist(methods=["GET"])
def download_attachment(ticket, file, organization=None):
    pu, customer = _ctx(organization)
    ratelimit.check("download", 60)
    helpdesk.assert_ticket_access(pu, ticket, customer)
    if not helpdesk.file_belongs_to_ticket(file, ticket):
        log_denied(pu, "File", file, "attachment not on ticket")
        raise PortalAccessError(_("Attachment not found."))
    stream_file(file)
