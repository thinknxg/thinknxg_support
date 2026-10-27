"""1.2: existing open conversations stay with people; create assistant defaults."""
import frappe

from thinknxg_support.install import ensure_ai_defaults


def execute():
    frappe.db.sql(
        "update `tabSupport Conversation Link` set handling = if(assigned_agent is null or assigned_agent = '', 'Queued', 'Agent') "
        "where coalesce(handling, '') = ''"
    )
    frappe.db.sql("update `tabSupport Portal Message` set sender_type = if(direction = 'Inbound', 'Customer', 'Agent') "
                  "where coalesce(sender_type, '') = ''")
    ensure_ai_defaults()
