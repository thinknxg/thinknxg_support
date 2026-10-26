import frappe

no_cache = 1
sitemap = 0


def get_context(context):
    s = frappe.get_cached_doc("Support Portal Settings")
    lang = None
    if frappe.session.user != "Guest":
        lang = frappe.db.get_value("Support Portal Profile", frappe.session.user, "language")
    lang = lang or s.default_language or "en"
    context.no_cache = 1
    context.lang = lang if lang in ("en", "ar") else "en"
    context.dir = "rtl" if context.lang == "ar" else "ltr"
    context.portal_title = s.portal_title or "thinkNXG Support"
    context.chat_title = s.chat_title or "Chat with support"
    context.primary_color = s.primary_color if str(s.primary_color or "").startswith("#") else "#0F766E"
    context.boot_json = frappe.as_json({"csrf_token": frappe.sessions.get_csrf_token(), "lang": context.lang},
                                       indent=None).replace("</", "<\\/")
    return context
