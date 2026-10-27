"""Live chat endpoints. Guest methods are rate limited per IP and authorise every call with the
chat token (header X-Support-Chat-Token or `token`). Customer methods use the normal portal checks."""
from __future__ import annotations

import frappe
from frappe import _

from thinknxg_support import ratelimit
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


@frappe.whitelist(allow_guest=True, methods=["GET"])
def state(conversation, token=None):
    ratelimit.check("chat_state", 240, 60)
    return live_chat.guest_state(conversation, _token(token))


@frappe.whitelist(allow_guest=True, methods=["POST"])
def send(conversation, message, token=None, client_message_id=None, payload=None):
    return live_chat.guest_send(conversation, _token(token), message, client_message_id, payload)


@frappe.whitelist(allow_guest=True, methods=["POST"])
def typing(conversation, token=None):
    ratelimit.check("chat_typing", 40, 60)
    return live_chat.guest_typing(conversation, _token(token))


@frappe.whitelist(allow_guest=True, methods=["POST"])
def feedback(conversation, message, value, token=None):
    conv = live_chat._guest_conv(conversation, _token(token))
    return live_chat.feedback(conv, message, value)


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


@frappe.whitelist(methods=["GET"])
def my_state(organization=None):
    ratelimit.check("chat_state", 240, 60)
    pu, customer = _customer(organization)
    return live_chat.customer_state(pu, customer)


@frappe.whitelist(methods=["POST"])
def customer_send(message, organization=None, client_message_id=None, payload=None):
    pu, customer = _customer(organization)
    return live_chat.customer_send(pu, customer, message, client_message_id, files=uploaded_files(), payload=payload)


@frappe.whitelist(methods=["POST"])
def customer_typing(organization=None):
    ratelimit.check("chat_typing", 40, 60)
    pu, customer = _customer(organization)
    return live_chat.customer_typing(pu, customer)


@frappe.whitelist(methods=["POST"])
def customer_feedback(message, value, organization=None):
    pu, customer = _customer(organization)
    return live_chat.customer_feedback(pu, customer, message, value)


@frappe.whitelist(methods=["POST"])
def customer_end(organization=None, rating=None):
    pu, customer = _customer(organization)
    return live_chat.customer_end(pu, customer, rating)
