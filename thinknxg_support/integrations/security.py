"""Security check for support staff accounts, with plain fixes. Reads settings; changes nothing on its own.

Two-factor in Frappe has two switches: System Settings > Enable Two Factor Auth, and "Two Factor Authentication"
on each role. Staff with a role that has it sign in with a code (authenticator app, e-mail or SMS, as set in
System Settings). The agent apps sign in through the same web login, so they get the same check.
"""
from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, get_url

SUPPORT_ROLES = ("Support Agent", "Support Manager", "Support Portal Administrator")


def _ss(field, default=None):
    try:
        v = frappe.db.get_single_value("System Settings", field)
    except Exception:
        return default
    return default if v is None else v


def _hours(expiry: str | None) -> float:
    try:
        h, m = (str(expiry or "170:00").split(":") + ["0"])[:2]
        return int(h) + int(m) / 60
    except ValueError:
        return 170


def staff_without_two_factor() -> int:
    if not cint(_ss("enable_two_factor_auth", 0)):
        return _staff_count()
    protected = {r for r in SUPPORT_ROLES if cint(frappe.db.get_value("Role", r, "two_factor_auth"))}
    unprotected = [r for r in SUPPORT_ROLES if r not in protected]
    if not unprotected:
        return 0
    users = set(frappe.get_all("Has Role", filters={"role": ["in", unprotected], "parenttype": "User"}, pluck="parent"))
    covered = set(frappe.get_all("Has Role", filters={"role": ["in", list(protected) or [""]], "parenttype": "User"},
                                 pluck="parent"))
    enabled = set(frappe.get_all("User", filters={"name": ["in", list(users - covered) or [""]], "enabled": 1},
                                 pluck="name"))
    return len(enabled - {"Administrator"})


def _staff_count() -> int:
    users = set(frappe.get_all("Has Role", filters={"role": ["in", list(SUPPORT_ROLES)], "parenttype": "User"},
                               pluck="parent"))
    return frappe.db.count("User", {"name": ["in", list(users) or [""]], "enabled": 1})


def checks() -> list[dict]:
    two_fa = cint(_ss("enable_two_factor_auth", 0))
    roles = {r: cint(frappe.db.get_value("Role", r, "two_factor_auth")) for r in SUPPORT_ROLES
             if frappe.db.exists("Role", r)}
    missing = staff_without_two_factor()
    hours = _hours(_ss("session_expiry", "170:00"))
    attempts = cint(_ss("allow_consecutive_login_attempts", 0))
    out = [
        {"key": "two_factor", "ok": bool(two_fa and all(roles.values())), "title": _("Two-factor sign-in for support staff"),
         "detail": _("{0} active staff accounts can sign in with a password alone.").format(missing) if missing
         else _("Every support role asks for a sign-in code."),
         "fix": _("Use the button below, or turn on System Settings > Enable Two Factor Auth and tick Two Factor "
                  "Authentication on the roles {0}. Staff then set up an authenticator app at their next sign-in "
                  "(the Windows, Android and iOS apps use the same web sign-in).").format(", ".join(SUPPORT_ROLES)),
         "action": "require_two_factor" if not (two_fa and all(roles.values())) else None},
        {"key": "password_policy", "ok": bool(cint(_ss("enable_password_policy", 0))
                                              and cint(_ss("minimum_password_score", 0)) >= 3),
         "title": _("Strong passwords"),
         "detail": _("Password policy is {0}, minimum score {1}.").format(
             _("on") if cint(_ss("enable_password_policy", 0)) else _("off"), _ss("minimum_password_score") or "-"),
         "fix": _("System Settings > Password: Enable Password Policy, Minimum Password Score 3 or higher.")},
        {"key": "lockout", "ok": attempts > 0 and attempts <= 10, "title": _("Lock out repeated failed sign-ins"),
         "detail": _("Allowed consecutive failed sign-ins: {0}.").format(attempts or _("unlimited")),
         "fix": _("System Settings > Login: Allow Consecutive Login Attempts 5 to 10.")},
        {"key": "session", "ok": hours <= 72, "title": _("Sessions expire"),
         "detail": _("Desk sessions last {0} hours without activity.").format(round(hours)),
         "fix": _("System Settings > Session Expiry: 24:00 or less for shared or public computers (the agent apps "
                  "keep their own revocable sign-in).")},
        {"key": "https", "ok": get_url().startswith("https://"), "title": _("Encrypted connection (HTTPS)"),
         "detail": get_url(),
         "fix": _("Serve the site over https; sign-in, chat and the agent apps need it in production.")},
    ]
    try:
        ai = frappe.get_cached_doc("Support AI Settings")
        out.append({"key": "ai_redaction", "ok": bool(cint(ai.get("redact_contact_details")) or not cint(ai.enable_ai)),
                    "title": _("Contact details removed before AI calls"),
                    "detail": _("On") if cint(ai.get("redact_contact_details")) else _("Off"),
                    "fix": _("Support AI Settings > Privacy: Remove Emails and Phone Numbers Before Sending.")})
    except Exception:
        pass
    return out


def require_two_factor_for_support_roles() -> list[dict]:
    """System Managers only: turn on two-factor and require it for the support roles. Logged."""
    frappe.only_for("System Manager")
    changed = []
    if not cint(_ss("enable_two_factor_auth", 0)):
        frappe.db.set_single_value("System Settings", "enable_two_factor_auth", 1)
        changed.append("System Settings")
    for r in SUPPORT_ROLES:
        if frappe.db.exists("Role", r) and not cint(frappe.db.get_value("Role", r, "two_factor_auth")):
            frappe.db.set_value("Role", r, "two_factor_auth", 1)
            changed.append(r)
    frappe.clear_cache()
    from thinknxg_support.audit import log_event

    log_event("Administrative Change", details={"two_factor_required_for": changed})
    return checks()
