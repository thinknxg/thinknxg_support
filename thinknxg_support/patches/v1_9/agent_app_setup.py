"""1.9: one client request id per conversation (duplicate-send protection) and Agent App defaults."""
import frappe


def execute():
    try:
        frappe.db.add_unique("Support Portal Message", ["conversation", "client_message_id"],
                             constraint_name="unique_conversation_client_message")
    except Exception:
        # existing duplicates block the constraint; the API still de-duplicates by lookup
        frappe.log_error(title="thinkNXG Support: unique client message index not added")
