# Copyright (c) 2026, Kreatao and contributors
import frappe
from frappe import _
from frappe.model.document import Document


class SupportAgentAppSettings(Document):
    def validate(self):
        for f in ("inbox_poll_seconds", "thread_poll_seconds", "alerts_poll_seconds"):
            self.set(f, max(2, min(300, self.get(f) or 10)))
        d = (self.desktop_redirect_uri or "").strip()
        if d and not (d.startswith("http://127.0.0.1:") or d.startswith("http://localhost:")):
            frappe.throw(_("The Windows sign-in address must be a loopback address (http://127.0.0.1:PORT/...)."))
        m = (self.mobile_redirect_uri or "").strip()
        if m and (m.startswith("http") or "://" not in m):
            frappe.throw(_("The mobile sign-in address must be an app scheme such as com.thinknxg.agent://oauth2redirect."))


@frappe.whitelist(methods=["POST"])
def create_oauth_client():
    frappe.only_for(["System Manager", "Support Portal Administrator"])
    from thinknxg_support.integrations import staff_auth

    return staff_auth.ensure_oauth_client(force=True)
