# Copyright (c) 2026, Kreatao and contributors
import frappe
from frappe import _
from frappe.model.document import Document


class SupportWhatsAppTemplate(Document):
    def before_naming(self):
        self.key = f"{self.template_name}-{self.language}"

    def validate(self):
        for v in self.variables or []:
            if v.source == "Fixed Text" and not (v.fixed_text or "").strip():
                frappe.throw(_("Row {0}: write the fixed text for {1}.").format(v.idx, v.key))
            if self.category == "Authentication" and v.source != "Entered by Agent":
                frappe.throw(_("The code in an authentication template is entered when it is sent."))
        if self.header_media_url and not self.header_media_url.lower().startswith("https://"):
            frappe.throw(_("The header media link must start with https://"))

    def on_update(self):
        frappe.clear_document_cache(self.doctype, self.name)


@frappe.whitelist(methods=["POST"])
def sync_templates():
    frappe.only_for(["System Manager", "Support Portal Administrator", "Support Manager"])
    from thinknxg_support.integrations import wa_templates

    return wa_templates.sync()
