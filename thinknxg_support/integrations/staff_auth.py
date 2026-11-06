"""Who may use the Agent Apps, and the OAuth client they sign in through.

Sign-in is Frappe's own OAuth 2 provider: authorization code with PKCE (S256) in the system browser. The app holds
no secret; the access token belongs to the agent's own Frappe user, so every permission and audit entry is theirs.
"""
from __future__ import annotations

import frappe
from frappe import _

SETTINGS = "Support Agent App Settings"
STAFF_ROLES_FALLBACK = ["Support Agent", "Support Manager", "Support Portal Administrator", "System Manager",
                        "Agent", "Agent Manager"]
MANAGER_ROLES = {"Support Manager", "Support Portal Administrator", "System Manager", "Agent Manager"}


class StaffAccessError(frappe.PermissionError):
    http_status_code = 403


def settings():
    return frappe.get_cached_doc(SETTINGS)


def staff_roles() -> list[str]:
    try:
        from thinknxg_support.integrations import alerts

        roles = alerts.agent_roles()
    except Exception:
        roles = []
    return list(dict.fromkeys([*roles, *STAFF_ROLES_FALLBACK]))


def is_staff(user: str | None = None) -> bool:
    user = user or frappe.session.user
    if not user or user == "Guest":
        return False
    if user == "Administrator":
        return True
    row = frappe.db.get_value("User", user, ["enabled", "user_type"], as_dict=True)
    if not (row and row.enabled and row.user_type == "System User"):
        return False
    return bool(set(staff_roles()) & set(frappe.get_roles(user)))


def is_manager(user: str | None = None) -> bool:
    user = user or frappe.session.user
    return user == "Administrator" or bool(MANAGER_ROLES & set(frappe.get_roles(user)))


def require_staff():
    """Every staff API call starts here: signed in, a desk (System) user, a staff role, apps allowed."""
    if frappe.session.user == "Guest":
        raise frappe.AuthenticationError(_("Sign in with your staff account."))
    if not is_staff():
        raise StaffAccessError(_("This account is not a support agent account."))
    if frappe.db.exists("DocType", SETTINGS) and not settings().enabled:
        raise StaffAccessError(_("The Agent Apps are switched off for this site."))


def redirect_uris() -> list[str]:
    s = settings()
    return [u for u in ((s.desktop_redirect_uri or "").strip(), (s.mobile_redirect_uri or "").strip()) if u]


def ensure_oauth_client(force: bool = False) -> dict:
    """Create (or update) the OAuth Client the apps use. Authorization code, no secret shipped in the apps."""
    s = frappe.get_single(SETTINGS)
    uris = redirect_uris() or ["http://127.0.0.1:43823/callback", "com.thinknxg.agent://oauth2redirect"]
    name = s.oauth_client if s.oauth_client and frappe.db.exists("OAuth Client", s.oauth_client) else None
    values = {"app_name": "thinkNXG Support Agent", "redirect_uris": "\n".join(uris), "default_redirect_uri": uris[0],
              "grant_type": "Authorization Code", "response_type": "Code", "scopes": "all openid",
              "skip_authorization": 0}
    meta = frappe.get_meta("OAuth Client")
    # Newer Frappe versions describe public clients explicitly; use it when the field exists
    if meta.has_field("token_endpoint_auth_method"):
        values["token_endpoint_auth_method"] = "None"  # public client: PKCE instead of a secret
    roles = []
    if meta.has_field("allowed_roles") and frappe.get_meta("OAuth Client Role").has_field("role"):
        # defence in depth: Frappe refuses tokens to accounts without a staff role (the staff API checks again)
        roles = [{"role": r} for r in staff_roles() if frappe.db.exists("Role", r)]
    if name:
        doc = frappe.get_doc("OAuth Client", name)
        if not force:
            return {"client_id": doc.client_id, "message": _("OAuth Client already set up.")}
        doc.update({k: v for k, v in values.items() if meta.has_field(k)})
        if roles:
            doc.set("allowed_roles", roles)
        doc.save(ignore_permissions=True)
    else:
        doc = frappe.get_doc({"doctype": "OAuth Client", **{k: v for k, v in values.items() if meta.has_field(k)}})
        if roles:
            doc.set("allowed_roles", roles)
        doc.insert(ignore_permissions=True)
        s.oauth_client = doc.name
        s.flags.ignore_permissions = True
        s.save()
    return {"client_id": doc.client_id,
            "message": _("OAuth Client {0} is ready. Sign-in addresses: {1}").format(doc.name, ", ".join(uris))}


def oauth_endpoints() -> dict:
    base = frappe.utils.get_url()
    m = "/api/method/frappe.integrations.oauth2."
    return {"authorize_url": base + m + "authorize", "token_url": base + m + "get_token",
            "revoke_url": base + m + "revoke_token", "userinfo_url": base + m + "openid_profile"}
