# Copyright (c) 2026, Kreatao and contributors
import frappe
from frappe.model.document import Document


class SupportConversationLink(Document):
    pass


@frappe.whitelist(methods=["GET"])
def get_thread(name: str):
    doc = frappe.get_doc("Support Conversation Link", name)
    doc.check_permission("read")
    msgs = frappe.get_all(
        "Support Portal Message",
        filters={"conversation": name},
        fields=["name", "direction", "sender", "sender_name", "content", "attachment",
                "is_internal", "creation"],
        order_by="creation asc",
        limit=500,
    )
    frappe.db.set_value("Support Conversation Link", name, "unread_agent", 0, update_modified=False)
    return msgs


@frappe.whitelist(methods=["POST"])
def agent_reply(name: str, content: str, internal: int = 0):
    doc = frappe.get_doc("Support Conversation Link", name)
    doc.check_permission("write")
    from thinknxg_support.integrations.conversations import post_agent_message

    return post_agent_message(doc, content, internal=int(internal or 0), source="desk")


@frappe.whitelist(methods=["POST"])
def escalate(name: str):
    doc = frappe.get_doc("Support Conversation Link", name)
    doc.check_permission("write")
    from thinknxg_support.integrations.conversations import escalate_to_ticket

    return escalate_to_ticket(doc, actor="agent")


@frappe.whitelist(methods=["POST"])
def link_customer(name: str, customer: str, contact: str | None = None):
    """Agent confirms who a guest / WhatsApp visitor is and attaches the chat to that customer."""
    doc = frappe.get_doc("Support Conversation Link", name)
    doc.check_permission("write")
    if not frappe.db.exists("Customer", customer):
        frappe.throw(frappe._("Customer not found."))
    if contact and not frappe.db.exists("Dynamic Link", {"parenttype": "Contact", "parent": contact,
                                                          "link_doctype": "Customer", "link_name": customer}):
        frappe.throw(frappe._("That contact is not linked to the selected customer."))
    doc.db_set({"customer": customer, "contact": contact or doc.contact})
    from thinknxg_support.audit import log_event

    log_event("Administrative Change", reference_doctype=doc.doctype, reference_name=doc.name,
              details={"linked_customer": customer})
    return {"ok": True}
