# Copyright (c) 2026, Kreatao and contributors
import frappe
from frappe import _
from frappe.model.document import Document


class SupportDownloadGrant(Document):
    def validate(self):
        if self.file and not self.file.startswith("/private/"):
            frappe.throw(_("Documents shared through the portal must be private files."))
