# Copyright (c) 2026, Kreatao and contributors
import frappe
from frappe import _
from frappe.model.document import Document

from thinknxg_support.integrations import privacy


class SupportPrivacyRequest(Document):
    def validate(self):
        self.email = (self.email or "").strip().lower() or None
        self.phone = privacy.digits(self.phone) or None
        if not (self.email or self.phone or self.customer):
            frappe.throw(_("Enter an e-mail, a phone number or a customer."))
        if self.status == "Completed" and not self.is_new():
            before = self.get_doc_before_save()
            if before and any(before.get(f) != self.get(f) for f in ("email", "phone", "customer", "request_type")):
                frappe.throw(_("A completed request cannot be changed. Create a new one."))


def _admin():
    frappe.only_for(["System Manager", "Support Portal Administrator"])


@frappe.whitelist(methods=["POST"])
def review(name: str):
    _admin()
    return privacy.review(name)


@frappe.whitelist(methods=["POST"])
def run(name: str, confirm: str | None = None):
    _admin()
    return privacy.run(name, confirm)
