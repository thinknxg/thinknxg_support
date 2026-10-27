"""Runtime detection of installed apps and their schema.

The Helpdesk and Raven schemas change between releases, so we never assume field
names: the resolved map is stored in Support Portal Settings.schema_map and
refreshed on install, migrate and on demand ("Verify Integrations").
"""
from __future__ import annotations

import json
from importlib import metadata

import frappe
from thinknxg_support.utils import _request_cache
from frappe.utils import now_datetime

HELPDESK_TICKET_FIELDS = [
    "subject", "description", "raised_by", "contact", "customer", "ticket_type", "priority",
    "agent_group", "status", "status_category", "opening_date", "response_by", "resolution_by",
    "agreement_status", "first_responded_on", "resolution_date", "feedback_rating", "feedback_text",
    "feedback", "via_customer_portal",
]
RAVEN_MESSAGE_FIELDS = ["channel_id", "text", "message_type", "is_bot_message", "bot", "file", "is_reply"]
RAVEN_CHANNEL_FIELDS = ["channel_name", "type", "channel_description", "workspace", "is_direct_message"]


def _app_version(app: str) -> str | None:
    try:
        return metadata.version(app)
    except Exception:
        try:
            return frappe.get_attr(f"{app}.__version__")
        except Exception:
            return None


def _fields(doctype: str, wanted: list[str]) -> dict:
    if not frappe.db.exists("DocType", doctype):
        return {}
    meta = frappe.get_meta(doctype)
    return {f: bool(meta.has_field(f)) for f in wanted}


def detect() -> dict:
    installed = set(frappe.get_installed_apps())
    out = {"apps": {}, "helpdesk": {}, "raven": {}, "erpnext": {}, "warnings": []}

    for app in ("frappe", "erpnext", "helpdesk", "raven"):
        out["apps"][app] = {"installed": app in installed, "version": _app_version(app) if app in installed else None}

    # ---- Helpdesk
    hd = out["helpdesk"]
    hd["ticket_doctype"] = "HD Ticket" if frappe.db.exists("DocType", "HD Ticket") else None
    hd["customer_doctype"] = "HD Customer" if frappe.db.exists("DocType", "HD Customer") else None
    hd["status_doctype"] = "HD Ticket Status" if frappe.db.exists("DocType", "HD Ticket Status") else None
    hd["article_doctype"] = "HD Article" if frappe.db.exists("DocType", "HD Article") else None
    hd["article_category_doctype"] = "HD Article Category" if frappe.db.exists("DocType", "HD Article Category") else None
    hd["ticket_fields"] = _fields("HD Ticket", HELPDESK_TICKET_FIELDS)
    hd["article_fields"] = _fields("HD Article", ["title", "content", "status", "published", "category", "author"])
    hd["category_fields"] = _fields("HD Article Category", ["category_name", "description"])
    try:
        from helpdesk.helpdesk.doctype.hd_ticket.hd_ticket import HDTicket  # type: ignore

        hd["reply_via_contact"] = hasattr(HDTicket, "reply_via_contact")
    except Exception:
        hd["reply_via_contact"] = False
    hd["ok"] = bool(hd["ticket_doctype"] and hd["ticket_fields"].get("raised_by") and hd["ticket_fields"].get("subject"))

    # ---- Raven
    rv = out["raven"]
    rv["channel_doctype"] = "Raven Channel" if frappe.db.exists("DocType", "Raven Channel") else None
    rv["message_doctype"] = "Raven Message" if frappe.db.exists("DocType", "Raven Message") else None
    rv["member_doctype"] = "Raven Channel Member" if frappe.db.exists("DocType", "Raven Channel Member") else None
    rv["bot_doctype"] = "Raven Bot" if frappe.db.exists("DocType", "Raven Bot") else None
    rv["message_fields"] = _fields("Raven Message", RAVEN_MESSAGE_FIELDS)
    rv["channel_fields"] = _fields("Raven Channel", RAVEN_CHANNEL_FIELDS)
    rv["ok"] = bool(rv["channel_doctype"] and rv["message_doctype"] and rv["member_doctype"]
                    and rv["message_fields"].get("channel_id") and rv["message_fields"].get("text"))

    # ---- ERPNext
    out["erpnext"] = {
        "ok": "erpnext" in installed,
        "subscription": bool(frappe.db.exists("DocType", "Subscription")),
    }

    settings = frappe.get_single("Support Portal Settings")
    if settings.enable_helpdesk and not hd["ok"]:
        out["warnings"].append("Helpdesk adapter is enabled but Frappe Helpdesk is not installed or incompatible. Ticketing is disabled until resolved.")
    if settings.enable_raven:
        if not rv["ok"]:
            out["warnings"].append("Raven bridge is enabled but Raven is not installed or incompatible. Conversations fall back to portal-native messaging.")
        elif not settings.raven_bot:
            out["warnings"].append("Raven bridge needs a Raven Bot (Support Portal Settings > Integrations). Conversations fall back to portal-native messaging.")
        elif rv["bot_doctype"] and not frappe.db.exists("Raven Bot", settings.raven_bot):
            out["warnings"].append(f"Raven Bot '{settings.raven_bot}' does not exist. Conversations fall back to portal-native messaging.")
    return out


def refresh(save: bool = True) -> dict:
    data = detect()
    summary = {
        "Helpdesk": _status_line(data["apps"]["helpdesk"], data["helpdesk"]["ok"]),
        "Raven": _status_line(data["apps"]["raven"], data["raven"]["ok"]),
        "ERPNext": _status_line(data["apps"]["erpnext"], data["erpnext"]["ok"]),
        "Warnings": len(data["warnings"]),
    }
    data["summary"] = summary
    if save:
        frappe.db.set_single_value(
            "Support Portal Settings",
            {
                "schema_map": json.dumps(data, indent=1, default=str),
                "helpdesk_status": summary["Helpdesk"],
                "raven_status": summary["Raven"],
                "last_verified_on": now_datetime(),
            },
        )
        frappe.clear_document_cache("Support Portal Settings", "Support Portal Settings")
    return data


def _status_line(app: dict, ok: bool) -> str:
    if not app["installed"]:
        return "Not installed"
    return f"{'Compatible' if ok else 'Installed but incompatible'} (v{app['version'] or '?'})"


def get() -> dict:
    """Cached schema map for the current request."""
    key = "thinknxg_support_schema"
    if key in _request_cache():
        return _request_cache()[key]
    raw = frappe.db.get_single_value("Support Portal Settings", "schema_map")
    try:
        data = json.loads(raw) if raw else None
    except ValueError:
        data = None
    if not data:
        data = refresh(save=False)
    _request_cache()[key] = data
    return data


def has_ticket_field(field: str) -> bool:
    return bool(get().get("helpdesk", {}).get("ticket_fields", {}).get(field))
