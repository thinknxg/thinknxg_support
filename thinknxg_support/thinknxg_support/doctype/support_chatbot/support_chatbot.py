# Copyright (c) 2026, Kreatao and contributors
import re

import frappe
from frappe import _
from frappe.model.document import Document


class SupportChatbot(Document):
    def validate(self):
        names = set()
        for r in self.rules:
            key = (r.rule_name or "").strip().lower()
            if key in names:
                frappe.throw(_("Rule name {0} is used twice.").format(r.rule_name))
            names.add(key)
            if r.trigger_type == "Regex":
                if len(r.trigger or "") > 200:
                    frappe.throw(_("Rule {0}: keep patterns under 200 characters.").format(r.rule_name))
                try:
                    re.compile(r.trigger or "")
                except re.error as e:
                    frappe.throw(_("Rule {0}: invalid pattern ({1}).").format(r.rule_name, e))
            if r.trigger_type != "Button Only" and not (r.trigger or "").strip():
                frappe.throw(_("Rule {0} needs a trigger.").format(r.rule_name))
        for text in [self.welcome_buttons] + [r.buttons for r in self.rules]:
            for line in (text or "").splitlines():
                if not line.strip():
                    continue
                if "|" not in line:
                    frappe.throw(_("Button lines need the form Label | rule name: {0}").format(line))
                target = line.split("|", 1)[1].strip().lower()
                if target not in ("@agent", "@ai") and target not in names:
                    frappe.throw(_("Button points to an unknown rule: {0}").format(target))
