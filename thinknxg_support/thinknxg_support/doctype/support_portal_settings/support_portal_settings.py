# Copyright (c) 2026, Kreatao and contributors
import frappe
from frappe import _
from frappe.model.document import Document


class SupportPortalSettings(Document):
    def validate(self):
        if self.max_attachment_mb and self.max_attachment_mb > 50:
            frappe.throw(_("Maximum attachment size cannot exceed 50 MB."))
        if self.enable_raven and self.raven_relay_mode == "Prefix Required" and not (self.raven_reply_prefix or "").strip():
            frappe.throw(_("Set a reply prefix or choose another relay mode."))
        self.whatsapp_webhook_url = frappe.utils.get_url(
            "/api/method/thinknxg_support.api.v1.whatsapp.webhook")
        if self.enable_whatsapp:
            missing = [label for field, label in (
                ("whatsapp_phone_number_id", _("Phone Number ID")),
                ("whatsapp_access_token", _("Access Token")),
                ("whatsapp_app_secret", _("App Secret")),
                ("whatsapp_verify_token", _("Webhook Verify Token")),
            ) if not self.get(field)]
            if missing:
                frappe.throw(_("To enable WhatsApp, fill in: {0}").format(", ".join(missing)))
        if self.whatsapp_display_number:
            digits = "".join(ch for ch in self.whatsapp_display_number if ch.isdigit())
            if len(digits) < 8:
                frappe.throw(_("Enter the WhatsApp number with its country code."))

    def on_update(self):
        from thinknxg_support.audit import log_event

        changed = [f for f in ("enable_helpdesk", "enable_raven", "require_contact_link",
                               "raven_relay_mode", "allowed_attachment_extensions", "enable_live_chat",
                               "allow_guest_chat", "enable_whatsapp", "whatsapp_phone_number_id")
                   if self.has_value_changed(f)]
        if changed:
            log_event("Administrative Change", reference_doctype=self.doctype,
                      reference_name=self.name, details={"changed": changed})
        frappe.clear_document_cache(self.doctype, self.name)


@frappe.whitelist(methods=["POST"])
def verify_integrations():
    frappe.only_for(["System Manager", "Support Portal Administrator"])
    from thinknxg_support.integrations import capabilities

    return capabilities.refresh(save=True)


@frappe.whitelist(methods=["POST"])
def test_whatsapp(to: str):
    frappe.only_for(["System Manager", "Support Portal Administrator"])
    from thinknxg_support.integrations import whatsapp

    return whatsapp.send_test(to)
