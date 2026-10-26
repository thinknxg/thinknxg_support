from urllib.parse import quote

import frappe

from thinknxg_support.constants import PORTAL_ROUTE

no_cache = 1
sitemap = 0


def get_context(context):
    if frappe.session.user == "Guest":
        path = frappe.local.request.path if getattr(frappe.local, "request", None) else PORTAL_ROUTE
        frappe.local.flags.redirect_location = "/login?redirect-to=" + quote(path)
        raise frappe.Redirect

    s = frappe.get_cached_doc("Support Portal Settings")
    lang = frappe.db.get_value("Support Portal Profile", frappe.session.user, "language") or s.default_language or "en"
    theme = frappe.db.get_value("Support Portal Profile", frappe.session.user, "theme") or "System"
    context.no_cache = 1
    context.lang = lang if lang in ("en", "ar") else "en"
    context.dir = "rtl" if context.lang == "ar" else "ltr"
    context.portal_title = s.portal_title or "thinkNXG Support"
    context.primary_color = (s.primary_color or "#0F766E") if str(s.primary_color or "").startswith("#") else "#0F766E"
    context.theme = theme.lower()
    boot = {
        "csrf_token": frappe.sessions.get_csrf_token(),
        "lang": context.lang,
        "base": PORTAL_ROUTE,
    }
    context.boot_json = frappe.as_json(boot, indent=None).replace("</", "<\\/")
    return context
