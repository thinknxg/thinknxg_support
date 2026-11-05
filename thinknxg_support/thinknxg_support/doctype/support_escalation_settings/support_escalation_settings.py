# Copyright (c) 2026, Kreatao and contributors
import frappe
from frappe import _
from frappe.model.document import Document


class SupportEscalationSettings(Document):
    def validate(self):
        seen = set()
        for t in self.targets:
            if t.priority in seen:
                frappe.throw(_("Priority {0} has two targets.").format(t.priority))
            seen.add(t.priority)
            if t.response_minutes <= 0 or t.resolution_minutes < t.response_minutes:
                frappe.throw(_("Row {0}: resolution must be at least the first-response time.").format(t.idx))
        for line in (self.notify_users or "").splitlines():
            if line.strip() and not frappe.db.exists("User", line.strip()):
                frappe.throw(_("User {0} not found.").format(line.strip()))
        for line in (self.whatsapp_numbers or "").splitlines():
            digits = "".join(c for c in line if c.isdigit())
            if line.strip() and not (8 <= len(digits) <= 15):
                frappe.throw(_("{0} is not a valid international phone number.").format(line.strip()))
