"""Support analytics for the desk page /app/support-analytics. Read-only; support managers only."""
from __future__ import annotations

import frappe

from thinknxg_support.integrations import analytics, limits, security


@frappe.whitelist(methods=["GET"])
def overview(from_date: str | None = None, to_date: str | None = None, channel: str | None = None,
             queue: str | None = None):
    analytics.require_manager()
    return analytics.overview(from_date, to_date, channel or None, queue or None)


@frappe.whitelist(methods=["GET"])
def agents(from_date: str | None = None, to_date: str | None = None, channel: str | None = None,
           queue: str | None = None):
    analytics.require_manager()
    return analytics.agents(from_date, to_date, channel or None, queue or None)


@frappe.whitelist(methods=["GET"])
def live():
    analytics.require_manager()
    return analytics.live()


@frappe.whitelist(methods=["GET"])
def usage():
    analytics.require_manager()
    return limits.status()


@frappe.whitelist(methods=["GET"])
def security_checks():
    analytics.require_manager()
    return security.checks()


@frappe.whitelist(methods=["POST"])
def require_two_factor():
    return security.require_two_factor_for_support_roles()


@frappe.whitelist(methods=["POST"])
def refresh():
    analytics.require_manager()
    analytics.refresh()
    return True
