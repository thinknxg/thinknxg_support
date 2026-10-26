from __future__ import annotations

import frappe

from thinknxg_support.security import get_portal_user, require_capability, resolve_organization


def context(organization: str | None = None, capability: str | None = None):
    pu = get_portal_user()
    org = organization or frappe.get_request_header("X-Support-Organization")
    customer = resolve_organization(pu, org)
    if capability:
        require_capability(pu, capability, customer)
    return pu, customer
