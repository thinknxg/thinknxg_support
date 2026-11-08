# Copyright (c) 2026, Kreatao and contributors
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint

from thinknxg_support.integrations import limits


class SupportUsageLimits(Document):
    def validate(self):
        plan = limits.plan()
        for key, label in limits.KEYS.items():
            value = cint(self.get(key))
            if value < 0:
                frappe.throw(_("{0} cannot be negative.").format(_(label)))
            cap = plan.get(key)
            if cap is not None and (value == 0 or value > cap):
                if value > cap:
                    frappe.msgprint(_("{0}: your hosting plan allows at most {1}, so {1} is used.")
                                    .format(_(label), cap), alert=True)
                self.set(key, cap)

    def on_update(self):
        from thinknxg_support.audit import log_event

        log_event("Administrative Change", reference_doctype=self.doctype, reference_name=self.name,
                  details={k: self.get(k) for k in limits.KEYS})
