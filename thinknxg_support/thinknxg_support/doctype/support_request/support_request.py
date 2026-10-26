# Copyright (c) 2026, Kreatao and contributors
import frappe
from frappe import _
from frappe.model.document import Document

ALLOWED_REFERENCES = {"Sales Order", "Sales Invoice", "Delivery Note", "Subscription", "Support Download Grant"}


class SupportRequest(Document):
    def validate(self):
        if self.reference_doctype and self.reference_doctype not in ALLOWED_REFERENCES:
            frappe.throw(_("Unsupported related document type."))

    def on_update(self):
        if self.has_value_changed("status") and not self.is_new():
            from thinknxg_support.integrations.notifications import notify_request_update

            notify_request_update(self)


@frappe.whitelist(methods=["POST"])
def escalate(name: str):
    doc = frappe.get_doc("Support Request", name)
    doc.check_permission("write")
    from thinknxg_support.integrations import helpdesk

    if doc.helpdesk_ticket:
        return doc.helpdesk_ticket
    ticket = helpdesk.create_ticket(
        subject=doc.subject,
        description=doc.details or doc.subject,
        raised_by=doc.raised_by,
        customer=doc.customer,
        via="escalation",
    )
    doc.db_set({"helpdesk_ticket": ticket, "status": "Escalated"})
    return ticket
