# Copyright (c) 2026, Kreatao and contributors
import frappe
from frappe import _
from frappe.model.document import Document


class SupportAgentShift(Document):
    def validate(self):
        if self.enabled and not self.slots:
            frappe.throw(_("Add at least one day with working hours, or untick Enabled."))
        for s in self.slots:
            if str(s.start_time) == str(s.end_time):
                frappe.throw(_("Row {0}: From and To are the same.").format(s.idx))

    def on_update(self):
        from thinknxg_support.integrations import presence

        presence.changed(self.user)
