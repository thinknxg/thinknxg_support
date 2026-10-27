"""Identity, organisation access and capability resolution.

Every portal API call goes through ``get_portal_user()`` and, when it touches an
organisation, ``require_capability()``. Client-supplied identifiers are never
trusted: they are resolved against the caller's explicit access grants.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import frappe
from thinknxg_support.utils import _request_cache
from frappe import _
from frappe.utils import getdate, nowdate

ACCESS_LEVELS = ("Self", "Organization Manager", "Billing", "Service")

# capability -> access levels that grant it
CAPABILITIES = {
    "tickets.own": ACCESS_LEVELS,
    "tickets.organization": ("Organization Manager",),
    "conversations.own": ACCESS_LEVELS,
    "conversations.organization": ("Organization Manager",),
    "services.request": ACCESS_LEVELS,
    "services.organization": ("Organization Manager", "Service"),
    "orders.read": ("Organization Manager", "Billing", "Service"),
    "invoices.read": ("Organization Manager", "Billing"),
    "statements.read": ("Organization Manager", "Billing"),
    "documents.read": ("Organization Manager", "Billing", "Service"),
    "members.read": ("Organization Manager",),
    "members.request": ("Organization Manager",),
}

STAFF_ROLES = {"Support Agent", "Support Manager", "Support Portal Administrator", "System Manager"}
ADMIN_ROLES = {"Support Portal Administrator", "System Manager"}


class PortalAccessError(frappe.PermissionError):
    pass


@dataclass
class Grant:
    name: str
    customer: str
    customer_name: str
    access_level: str


@dataclass
class PortalUser:
    user: str
    email: str
    full_name: str
    roles: set
    contacts: list = field(default_factory=list)
    grants: list = field(default_factory=list)

    @property
    def is_staff(self) -> bool:
        return bool(self.roles & STAFF_ROLES)

    @property
    def is_admin(self) -> bool:
        return bool(self.roles & ADMIN_ROLES)

    @property
    def customers(self) -> list[str]:
        seen = []
        for g in self.grants:
            if g.customer not in seen:
                seen.append(g.customer)
        return seen

    def levels_for(self, customer: str) -> set:
        return {g.access_level for g in self.grants if g.customer == customer}

    def can(self, capability: str, customer: str) -> bool:
        allowed = CAPABILITIES.get(capability)
        if not allowed:
            return False
        return bool(self.levels_for(customer) & set(allowed))

    def capabilities_for(self, customer: str) -> list[str]:
        return sorted(c for c in CAPABILITIES if self.can(c, customer))


def get_portal_user(allow_staff_without_grant: bool = False) -> PortalUser:
    """Resolve the session user to a portal identity or raise."""
    user = frappe.session.user
    if not user or user == "Guest":
        raise frappe.AuthenticationError(_("Please log in to use the support portal."))

    cache_key = f"thinknxg_support:pu:{user}"
    cached = _request_cache().get(cache_key)
    if cached:
        return cached

    u = frappe.db.get_value("User", user, ["name", "email", "full_name", "enabled"], as_dict=True)
    if not u or not u.enabled:
        raise frappe.AuthenticationError(_("Your account is disabled."))

    pu = PortalUser(
        user=u.name,
        email=u.email or u.name,
        full_name=u.full_name or u.name,
        roles=set(frappe.get_roles(user)),
    )
    pu.contacts = _contacts_for_user(pu)
    pu.grants = _grants_for_user(pu)

    if not pu.grants and not (allow_staff_without_grant and pu.is_staff):
        raise PortalAccessError(
            _("Your account is not yet linked to an authorised organisation. Please contact support.")
        )

    _request_cache()[cache_key] = pu
    return pu


def _contacts_for_user(pu: PortalUser) -> list[str]:
    names = frappe.get_all("Contact", filters={"user": pu.user}, pluck="name")
    if not names and pu.email:
        names = frappe.get_all(
            "Contact Email", filters={"email_id": pu.email, "parenttype": "Contact"}, pluck="parent"
        )
    return list(dict.fromkeys(names))


def _contact_customers(contacts: list[str]) -> set:
    if not contacts:
        return set()
    return set(
        frappe.get_all(
            "Dynamic Link",
            filters={"parenttype": "Contact", "parent": ["in", contacts], "link_doctype": "Customer"},
            pluck="link_name",
        )
    )


def _grants_for_user(pu: PortalUser) -> list[Grant]:
    today = getdate(nowdate())
    rows = frappe.get_all(
        "Support Organization Access",
        filters={"user": pu.user, "enabled": 1, "docstatus": ["<", 2]},
        fields=["name", "customer", "access_level", "valid_from", "valid_until", "approved_by"],
        order_by="creation asc",
    )
    require_contact = frappe.db.get_single_value("Support Portal Settings", "require_contact_link")
    contact_customers = _contact_customers(pu.contacts) if require_contact else None

    grants = []
    for r in rows:
        if not r.approved_by:
            continue
        if r.valid_from and getdate(r.valid_from) > today:
            continue
        if r.valid_until and getdate(r.valid_until) < today:
            continue
        if contact_customers is not None and r.customer not in contact_customers:
            continue
        if frappe.db.get_value("Customer", r.customer, "disabled"):
            continue
        grants.append(
            Grant(
                name=r.name,
                customer=r.customer,
                customer_name=frappe.db.get_value("Customer", r.customer, "customer_name") or r.customer,
                access_level=r.access_level,
            )
        )
    return grants


def resolve_organization(pu: PortalUser, organization: str | None = None) -> str:
    """Return a customer the user is authorised for. Never trusts the input blindly."""
    if organization:
        if organization not in pu.customers:
            log_denied(pu, "Customer", organization, "organization not granted")
            raise PortalAccessError(_("You are not authorised for this organisation."))
        return organization
    default = frappe.db.get_value("Support Portal Profile", pu.user, "default_customer")
    if default and default in pu.customers:
        return default
    if pu.customers:
        return pu.customers[0]
    raise PortalAccessError(_("No authorised organisation."))


def require_capability(pu: PortalUser, capability: str, customer: str) -> None:
    if customer not in pu.customers or not pu.can(capability, customer):
        log_denied(pu, "Customer", customer, f"missing capability {capability}")
        raise PortalAccessError(_("You do not have access to this information."))


def log_denied(pu: PortalUser | None, ref_doctype: str | None, ref_name: str | None, reason: str):
    from thinknxg_support.audit import log_event

    log_event(
        "Access Denied",
        severity="Warning",
        reference_doctype=ref_doctype,
        reference_name=ref_name,
        details=reason,
        user=pu.user if pu else frappe.session.user,
    )


def on_user_trash(doc, method=None):
    for name in frappe.get_all("Support Organization Access", filters={"user": doc.name}, pluck="name"):
        frappe.delete_doc("Support Organization Access", name, ignore_permissions=True, force=True)
