import frappe


class Conflict(frappe.ValidationError):
    """Someone else changed the record first (claim, transfer, status). The client reloads and shows `current`."""
    http_status_code = 409

    def __init__(self, message, current=None):
        super().__init__(message)
        frappe.local.response["error_code"] = "conflict"
        frappe.local.response["error_message"] = str(message)
        frappe.local.response["conflict"] = current or {}


class ChannelActionRequired(frappe.ValidationError):
    """The channel needs something else (e.g. the WhatsApp 24-hour window has closed). `actions` lists what the
    server offers."""
    http_status_code = 422

    def __init__(self, message, code, actions=None):
        super().__init__(message)
        frappe.local.response["error_code"] = code
        frappe.local.response["error_message"] = str(message)
        frappe.local.response["actions"] = actions or []
