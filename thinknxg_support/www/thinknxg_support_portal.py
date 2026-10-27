from urllib.parse import quote

import frappe

from thinknxg_support.constants import PORTAL_ROUTE

no_cache = 1
sitemap = 0


def get_context(context):
    s = frappe.get_cached_doc("Support Portal Settings")
    path = (frappe.local.request.path if getattr(frappe.local, "request", None) else PORTAL_ROUTE).rstrip("/") or PORTAL_ROUTE
    public_paths = {PORTAL_ROUTE} if s.landing_enabled else set()
    if s.public_knowledge and s.landing_enabled:
        public_paths.add(PORTAL_ROUTE + "/knowledge")
    is_public = path in public_paths or (s.public_knowledge and s.landing_enabled
                                         and path.startswith(PORTAL_ROUTE + "/knowledge/"))
    if frappe.session.user == "Guest" and not is_public:
        frappe.local.flags.redirect_location = "/login?redirect-to=" + quote(path)
        raise frappe.Redirect
    context.robots = "index, follow" if (s.index_landing and path == PORTAL_ROUTE) else "noindex, nofollow"
    context.meta_description = (s.meta_description or "")[:300]

    user = frappe.session.user
    lang = frappe.db.get_value("Support Portal Profile", user, "language") if user != "Guest" else None
    lang = lang or s.default_language or "en"
    theme = (frappe.db.get_value("Support Portal Profile", user, "theme") if user != "Guest" else None) or "System"
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
