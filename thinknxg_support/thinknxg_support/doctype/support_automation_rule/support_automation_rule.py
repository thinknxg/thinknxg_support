# Copyright (c) 2026, Kreatao and contributors
import frappe
from frappe import _
from frappe.model.document import Document

ALLOWED = {
    "Visitor on a Page": {"Send Message"},
    "Customer Quiet": {"Send Message", "Close Chat", "Notify or Escalate"},
    "Chat Closed Needing Follow-up": {"Create Follow-up Task", "Notify or Escalate"},
    "New Chat Outside Chat Hours": {"Send Message", "Collect Details"},
}


class SupportAutomationRule(Document):
    def validate(self):
        if self.action not in ALLOWED.get(self.trigger, set()):
            frappe.throw(_("{0} cannot be used with {1}. Choose one of: {2}.").format(
                _(self.action), _(self.trigger), ", ".join(_(a) for a in sorted(ALLOWED[self.trigger]))))
        if self.action in ("Send Message",) and not (self.message or "").strip():
            frappe.throw(_("Write the message to send."))
        if not (self.channel_live_chat or self.channel_whatsapp or self.channel_portal):
            frappe.throw(_("Choose at least one channel."))
        if self.trigger == "Visitor on a Page":
            if not self.channel_live_chat:
                frappe.throw(_("A message on a page is shown in the website chat: tick Live Chat."))
            self.seconds_on_page = min(max(self.seconds_on_page or 20, 3), 600)
        if self.trigger == "Customer Quiet":
            self.quiet_minutes = min(max(self.quiet_minutes or 10, 2), 1440)
        self.task_days = min(max(self.task_days or 1, 0), 60)
