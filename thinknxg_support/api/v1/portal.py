from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, now_datetime

from thinknxg_support.integrations import capabilities, helpdesk, raven
from thinknxg_support.security import PortalAccessError, get_portal_user
from thinknxg_support.utils import module_enabled, settings

LANGS = ("en", "ar")


@frappe.whitelist(methods=["GET"])
def boot():
    """Everything the SPA needs to render its shell."""
    s = settings()
    caps = capabilities.get()
    branding = {
        "title": s.portal_title or "thinkNXG Support",
        "logo": s.logo or "/assets/thinknxg_support/images/logo.svg",
        "primary_color": s.primary_color or "#0F766E",
        "support_email": s.support_email,
        "support_phone": s.support_phone,
        "footer_text": s.footer_text,
    }
    try:
        pu = get_portal_user(allow_staff_without_grant=True)
    except PortalAccessError as e:
        return {"linked": False, "message": str(e), "branding": branding, "user": frappe.session.user}

    available = {
        "tickets": module_enabled("tickets") and helpdesk.available(),
        "knowledge": module_enabled("knowledge") and helpdesk.kb_available(),
        "conversations": module_enabled("conversations"),
        "services": module_enabled("services"),
        "account": module_enabled("account"),
        "documents": module_enabled("documents"),
    }
    orgs = [
        {
            "customer": c,
            "customer_name": next(g.customer_name for g in pu.grants if g.customer == c),
            "access_levels": sorted(pu.levels_for(c)),
            "capabilities": pu.capabilities_for(c),
        }
        for c in pu.customers
    ]
    profile = frappe.db.get_value("Support Portal Profile", pu.user,
                                  ["default_customer", "language", "time_zone", "theme"], as_dict=True) or {}
    if pu.grants:
        _touch_profile(pu.user)

    out = {
        "linked": bool(pu.grants),
        "user": {"name": pu.user, "full_name": pu.full_name, "email": pu.email,
                 "is_staff": pu.is_staff, "is_admin": pu.is_admin},
        "organizations": orgs,
        "default_organization": profile.get("default_customer") if profile.get("default_customer") in pu.customers else (pu.customers[0] if pu.customers else None),
        "language": profile.get("language") or s.default_language or "en",
        "theme": profile.get("theme") or "System",
        "modules": available,
        "messaging_provider": "Raven" if raven.available() else "Portal Native",
        "branding": branding,
        "max_attachment_mb": cint(s.max_attachment_mb) or 10,
        "allowed_extensions": s.allowed_attachment_extensions,
        "helpdesk_agent_url": "/helpdesk" if pu.is_staff and helpdesk.available() else None,
    }
    if pu.is_admin:
        warnings = list(caps.get("warnings") or [])
        if module_enabled("tickets") and not helpdesk.available():
            warnings.append(_("Tickets module is enabled but the Helpdesk adapter is unavailable."))
        if module_enabled("knowledge") and not helpdesk.kb_available():
            warnings.append(_("Knowledge module is enabled but no Helpdesk knowledge base was found."))
        out["admin_warnings"] = list(dict.fromkeys(warnings))
    return out


def _touch_profile(user: str):
    if frappe.db.exists("Support Portal Profile", user):
        frappe.db.set_value("Support Portal Profile", user, "last_portal_login", now_datetime(), update_modified=False)
    else:
        frappe.get_doc({"doctype": "Support Portal Profile", "user": user,
                        "last_portal_login": now_datetime()}).insert(ignore_permissions=True)


@frappe.whitelist(methods=["GET"])
def organizations():
    pu = get_portal_user()
    return [{"customer": g.customer, "customer_name": g.customer_name, "access_level": g.access_level}
            for g in pu.grants]
