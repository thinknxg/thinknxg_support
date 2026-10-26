"""Auditable security / integration events. Never log secrets or message bodies."""
import json

import frappe

SENSITIVE_KEYS = {"password", "pwd", "token", "api_key", "api_secret", "secret", "authorization", "otp"}


def _clean(details):
    if details is None:
        return None
    if isinstance(details, dict):
        details = {k: ("***" if k.lower() in SENSITIVE_KEYS else v) for k, v in details.items()}
        details = json.dumps(details, default=str)
    return str(details)[:2000]


def log_event(event_type, severity="Info", reference_doctype=None, reference_name=None,
              details=None, user=None, commit=False):
    try:
        ip = getattr(frappe.local, "request_ip", None)
        frappe.get_doc(
            {
                "doctype": "Support Portal Event",
                "event_type": event_type,
                "severity": severity,
                "user": user or frappe.session.user,
                "ip_address": ip,
                "reference_doctype": reference_doctype if reference_doctype and frappe.db.exists("DocType", reference_doctype) else None,
                "reference_name": reference_name,
                "details": _clean(details),
            }
        ).insert(ignore_permissions=True)
        if commit:
            frappe.db.commit()
    except Exception:
        # auditing must never break the request path
        frappe.logger("thinknxg_support").exception("failed to write portal event")
