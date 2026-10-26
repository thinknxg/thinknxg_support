# Copyright (c) 2026, Kreatao and contributors
import frappe
from frappe import _
from frappe.model.document import Document


class SupportService(Document):
    def validate(self):
        if self.eligibility == "Customer Group" and not self.customer_group:
            frappe.throw(_("Select a Customer Group."))
        if self.eligibility == "Selected Customers" and not self.customers:
            frappe.throw(_("Add at least one customer."))

    def is_eligible(self, customer: str) -> bool:
        if not self.enabled:
            return False
        if self.eligibility == "All Customers":
            return True
        if self.eligibility == "Customer Group":
            return frappe.db.get_value("Customer", customer, "customer_group") == self.customer_group
        return any(r.customer == customer for r in self.customers)
