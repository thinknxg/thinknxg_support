"""Live chat endpoints. Guest methods are rate limited per IP and authorise every call with the
chat token (header X-Support-Chat-Token or `token`). Customer methods use the normal portal checks."""
from __future__ import annotations

import frappe
from frappe import _

from thinknxg_support.api.v1._base import context
from thinknxg_support.integrations import live_chat
from thinknxg_support.utils import uploaded_files


def _token(token=None):
    return token or frappe.get_request_header("X-Support-Chat-Token") or ""


@frappe.whitelist(allow_guest=True, methods=["GET"])
def config(context_name: str = "website"):
    return live_chat.widget_config(context_name)


@frappe.whitelist(allow_guest=True, methods=["POST"])
def start(message, name=None, email=None, phone=None, page=None, client_message_id=None, website=None):
    if website:  # honeypot field: hidden from people, filled in by bots
        frappe.throw(_("Please try again."), frappe.ValidationError)
    return live_chat.start_guest(message, name=name, email=email, phone=phone, page=page,
                                 client_message_id=client_message_id)


@frappe.whitelist(allow_guest=True, methods=["GET"])
def messages(conversation, token=None):
    return live_chat.guest_messages(conversation, _token(token))


@frappe.whitelist(allow_guest=True, methods=["POST"])
def send(conversation, message, token=None, client_message_id=None):
    return live_chat.guest_send(conversation, _token(token), message, client_message_id)


@frappe.whitelist(allow_guest=True, methods=["POST"])
def end(conversation, token=None, rating=None):
    return live_chat.guest_end(conversation, _token(token), rating)


def _customer(organization):
    if not frappe.db.get_single_value("Support Portal Settings", "enable_live_chat"):
        frappe.throw(_("Live chat is not enabled."), frappe.PermissionError)
    return context(organization, "conversations.own")


@frappe.whitelist(methods=["GET"])
def my_chat(organization=None):
    pu, customer = _customer(organization)
    return live_chat.customer_chat(pu, customer)


@frappe.whitelist(methods=["POST"])
def customer_send(message, organization=None, client_message_id=None):
    pu, customer = _customer(organization)
    return live_chat.customer_send(pu, customer, message, client_message_id, files=uploaded_files())


@frappe.whitelist(methods=["POST"])
def customer_end(organization=None, rating=None):
    pu, customer = _customer(organization)
    return live_chat.customer_end(pu, customer, rating)
