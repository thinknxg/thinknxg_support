# Copyright (c) 2026, Kreatao and contributors
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, now_datetime

APPROVER_ROLES = {"System Manager", "Support Portal Administrator"}


class SupportOrganizationAccess(Document):
    def validate(self):
        if self.valid_from and self.valid_until and getdate(self.valid_until) < getdate(self.valid_from):
            frappe.throw(_("Valid Until cannot be before Valid From."))
        dup = frappe.db.exists(
            "Support Organization Access",
            {"user": self.user, "customer": self.customer, "access_level": self.access_level,
             "name": ["!=", self.name]},
        )
        if dup:
            frappe.throw(_("This access level already exists for the user ({0}).").format(dup))
        if self.enabled and (self.is_new() or self.has_value_changed("enabled") or not self.approved_by):
            if not (set(frappe.get_roles()) & APPROVER_ROLES) and not self.flags.system_approved:
                frappe.throw(_("Only a Support Portal Administrator can enable portal access."))
            self.approved_by = frappe.session.user
            self.approved_on = now_datetime()
        if not self.enabled and self.has_value_changed("enabled"):
            self.approved_by = None
            self.approved_on = None

    def on_update(self):
        from thinknxg_support.audit import log_event

        if self.has_value_changed("enabled") or self.has_value_changed("access_level") or self.is_new():
            log_event("Administrative Change", reference_doctype=self.doctype, reference_name=self.name,
                      details={"user": self.user, "customer": self.customer,
                               "level": self.access_level, "enabled": self.enabled})
        self._ensure_role()

    def _ensure_role(self):
        if not self.enabled:
            return
        user = frappe.get_doc("User", self.user)
        wanted = {"Support Portal Customer"}
        if self.access_level == "Organization Manager":
            wanted.add("Support Organization Manager")
        if self.access_level == "Billing":
            wanted.add("Support Billing Contact")
        missing = wanted - set(r.role for r in user.roles)
        if missing:
            user.flags.ignore_permissions = True
            user.add_roles(*missing)
