# Copyright (c) 2026, Kreatao and contributors
import re

import frappe
from frappe import _
from frappe.model.document import Document


class SupportCannedResponse(Document):
    def validate(self):
        if self.shortcut:
            self.shortcut = self.shortcut.strip().lstrip("/").lower()
            if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,29}", self.shortcut):
                frappe.throw(_("Shortcut: letters, numbers, - or _ only (up to 30), no spaces."))
            clash = frappe.db.get_value("Support Canned Response",
                                        {"shortcut": self.shortcut, "name": ["!=", self.name], "enabled": 1,
                                         "visibility": "Team"}, "title")
            if clash and self.visibility == "Team":
                frappe.throw(_("/{0} is already used by {1}.").format(self.shortcut, clash))
        from thinknxg_support.utils import clean_html

        self.content = clean_html(self.content or "")
