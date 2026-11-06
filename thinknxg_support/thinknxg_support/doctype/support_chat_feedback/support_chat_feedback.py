# Copyright (c) 2026, Kreatao and contributors
import frappe
from frappe.model.document import Document


class SupportChatFeedback(Document):
    def validate(self):
        if self.has_value_changed("reviewed") and self.reviewed:
            self.reviewed_by = frappe.session.user
