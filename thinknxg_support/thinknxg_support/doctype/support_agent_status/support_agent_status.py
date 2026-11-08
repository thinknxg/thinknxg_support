# Copyright (c) 2026, Kreatao and contributors
import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime


class SupportAgentStatus(Document):
    def validate(self):
        if self.is_new() or self.has_value_changed("status"):
            self.set_on = now_datetime()
            self.set_by = frappe.session.user

    def on_update(self):
        from thinknxg_support.integrations import presence

        presence.changed(self.user)
