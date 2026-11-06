"""1.9: the Agent Apps' OAuth Client stored its sign-in addresses one per line, but Frappe expects them separated by
spaces, so sign-in failed with "Mismatching redirect URI". Rewrite them space-separated."""
import frappe


def execute():
    if not frappe.db.exists("DocType", "Support Agent App Settings"):
        return
    from thinknxg_support.integrations import staff_auth

    for field, default in (("desktop_redirect_uri", staff_auth.DEFAULT_DESKTOP_REDIRECT),
                           ("mobile_redirect_uri", staff_auth.DEFAULT_MOBILE_REDIRECT)):
        if not (frappe.db.get_single_value("Support Agent App Settings", field) or "").strip():
            frappe.db.set_single_value("Support Agent App Settings", field, default)  # settings never saved
    name = frappe.db.get_single_value("Support Agent App Settings", "oauth_client")
    if not name or not frappe.db.exists("OAuth Client", name):
        return
    raw = frappe.db.get_value("OAuth Client", name, "redirect_uris") or ""
    uris = " ".join(u for u in raw.split() if u)
    if uris != raw:
        frappe.db.set_value("OAuth Client", name, "redirect_uris", uris)
