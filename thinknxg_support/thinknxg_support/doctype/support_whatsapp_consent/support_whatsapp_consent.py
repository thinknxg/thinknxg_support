# Copyright (c) 2026, Kreatao and contributors
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime


class SupportWhatsAppConsent(Document):
    def before_naming(self):
        self.number = "".join(c for c in (self.number or "") if c.isdigit()).lstrip("0")

    def before_validate(self):
        self.before_naming()

    def validate(self):
        if len(self.number) < 8:
            frappe.throw(_("Enter the number with its country code."))
        if self.has_value_changed("status") or self.is_new():
            self.changed_on, self.changed_by = now_datetime(), frappe.session.user
        if self.status == "Opted In" and not (self.note or "").strip() and self.source in ("Agent", "Manager", None):
            frappe.throw(_("Write how the customer agreed to receive marketing messages."))

    def on_update(self):
        if not self.is_new() and self.has_value_changed("status"):
            from thinknxg_support.audit import log_event

            log_event("Administrative Change", reference_doctype=self.doctype, reference_name=self.name,
                      details={"whatsapp_consent": self.status, "source": self.source})
