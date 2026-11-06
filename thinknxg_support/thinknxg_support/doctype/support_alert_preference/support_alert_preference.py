# Copyright (c) 2026, Kreatao and contributors
import frappe
from frappe import _
from frappe.model.document import Document

KINDS = ['New Chat', 'Chat Message', 'New Ticket', 'Ticket Assigned', 'Conversation Message', 'Escalation', 'Negative Feedback', 'Positive Feedback']


class SupportAlertPreference(Document):
    def validate(self):
        managers = {"Support Manager", "Support Portal Administrator", "System Manager"}
        if self.user != frappe.session.user and not managers & set(frappe.get_roles()):
            frappe.throw(_("You can only change your own alert preferences."), frappe.PermissionError)
        self.volume = max(0, min(100, self.volume if self.volume is not None else 80))
        have = {i.kind for i in self.items}
        for k in KINDS:
            if k not in have:
                self.append("items", {"kind": k})

    def on_update(self):
        frappe.publish_realtime("thinknxg_support_alert_config", {}, user=self.user)
