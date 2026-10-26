from __future__ import annotations

import frappe
from frappe import _

from thinknxg_support import ratelimit
from thinknxg_support.api.v1._base import context
from thinknxg_support.integrations import conversations as svc
from thinknxg_support.security import PortalAccessError, log_denied
from thinknxg_support.utils import require_module, settings, uploaded_files


def _ctx(organization):
    require_module("conversations")
    return context(organization, "conversations.own")


@frappe.whitelist(methods=["GET"])
def list_conversations(organization=None):
    pu, customer = _ctx(organization)
    return svc.list_conversations(pu, customer)


@frappe.whitelist(methods=["GET"])
def unread(organization=None):
    pu, customer = _ctx(organization)
    return {"unread": svc.unread_total(pu, customer)}


@frappe.whitelist(methods=["POST"])
def start_conversation(subject, message, organization=None, conversation_type="Customer Chat",
                       visibility="Participant", client_message_id=None):
    pu, customer = _ctx(organization)
    ratelimit.check("ticket", settings().ticket_rate_limit)
    if visibility == "Organization" and not pu.can("conversations.organization", customer):
        visibility = "Participant"
    return svc.start(pu, customer, subject, message, conversation_type, visibility, client_message_id,
                     files=uploaded_files())


@frappe.whitelist(methods=["GET"])
def get_messages(conversation, organization=None):
    pu, customer = _ctx(organization)
    conv = svc.assert_conversation(pu, conversation, customer)
    return {
        "conversation": {"name": conv.name, "subject": conv.subject, "status": conv.status,
                         "helpdesk_ticket": conv.helpdesk_ticket, "conversation_type": conv.conversation_type},
        "messages": svc.messages(pu, conv),
    }


@frappe.whitelist(methods=["POST"])
def send_message(conversation, message, organization=None, client_message_id=None):
    pu, customer = _ctx(organization)
    ratelimit.check("message", settings().message_rate_limit)
    conv = svc.assert_conversation(pu, conversation, customer)
    return svc.post_customer_message(pu, conv, message, client_message_id, files=uploaded_files())


@frappe.whitelist(methods=["POST"])
def escalate(conversation, organization=None):
    pu, customer = _ctx(organization)
    conv = svc.assert_conversation(pu, conversation, customer)
    return {"ticket": svc.escalate_to_ticket(conv, actor="customer", pu=pu)}


@frappe.whitelist(methods=["POST"])
def close(conversation, organization=None):
    pu, customer = _ctx(organization)
    conv = svc.assert_conversation(pu, conversation, customer)
    if conv.started_by != pu.user:
        raise PortalAccessError(_("Only the person who started this conversation can close it."))
    conv.db_set("status", "Closed")
    return {"ok": True}


@frappe.whitelist(methods=["GET"])
def download_attachment(message, organization=None):
    pu, customer = _ctx(organization)
    ratelimit.check("download", 60)
    row = frappe.db.get_value("Support Portal Message", message, ["conversation", "attachment", "is_internal"],
                              as_dict=True)
    if not row or row.is_internal or not row.attachment:
        log_denied(pu, None, message, "message attachment denied")
        raise PortalAccessError(_("Attachment not found."))
    svc.assert_conversation(pu, row.conversation, customer)
    file_name = frappe.db.get_value("File", {"file_url": row.attachment, "attached_to_doctype": "Support Portal Message",
                                             "attached_to_name": message})
    if not file_name:
        raise PortalAccessError(_("Attachment not found."))
    from thinknxg_support.utils import stream_file

    stream_file(file_name)
