# Copyright (c) 2026, Kreatao and contributors
import frappe
from frappe import _
from frappe.model.document import Document


class SupportAlertSettings(Document):
    def validate(self):
        seen = set()
        for r in self.rules:
            if r.kind in seen:
                frappe.throw(_("{0} is listed twice.").format(r.kind))
            seen.add(r.kind)
            r.volume = max(0, min(100, r.volume or 0))
            if r.repeat_until_ack and (r.repeat_seconds or 0) < 5:
                frappe.throw(_("{0}: repeat every 5 seconds or more.").format(r.kind))

    def on_update(self):
        frappe.publish_realtime("thinknxg_support_alert_config", {})
