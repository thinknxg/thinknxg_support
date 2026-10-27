from __future__ import annotations

import frappe

from thinknxg_support.api.v1._base import context
from thinknxg_support.integrations import conversations, erpnext, helpdesk, knowledge
from thinknxg_support.utils import module_enabled, settings


@frappe.whitelist(methods=["GET"])
def get_dashboard(organization: str | None = None):
    pu, customer = context(organization)
    s = settings()
    out = {"organization": customer, "capabilities": pu.capabilities_for(customer)}

    if module_enabled("tickets") and helpdesk.available():
        out["tickets"] = helpdesk.counts(pu, customer)
    if module_enabled("conversations"):
        out["unread_messages"] = conversations.unread_total(pu, customer)
        out["recent_conversations"] = conversations.list_conversations(pu, customer)[:5]
    if module_enabled("account") and pu.can("statements.read", customer):
        out["statement"] = erpnext.statement(pu, customer)["totals"]
    if module_enabled("account") and pu.can("orders.read", customer):
        out["open_orders"] = erpnext.list_orders(pu, customer, page_length=5,
                                                 status=None)[:5]
    if module_enabled("services"):
        out["recent_requests"] = frappe.get_all(
            "Support Request", filters={"customer": customer, "raised_by": pu.user},
            fields=["name", "subject", "status", "modified"], order_by="modified desc", limit=5)
    if module_enabled("knowledge") and knowledge.available():
        try:
            out["articles"] = knowledge.search_articles(None, limit=5, audience="Customers")
        except Exception:
            out["articles"] = []
    if s.show_announcement and s.announcement:
        out["announcement"] = frappe.utils.strip_html(s.announcement)
    return out
