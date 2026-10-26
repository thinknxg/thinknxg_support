"""Notification dispatcher. Portal notifications use Frappe Notification Log
(type 'Alert', which Frappe does not email); email delivery is controlled by
Support Notification Preference. Helpdesk already emails agent replies, so
reply events are portal-only to avoid duplicate emails.
"""
from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint

from thinknxg_support.constants import PORTAL_ROUTE

PORTAL_DOCTYPES = ("HD Ticket", "Support Conversation Link", "Support Request", "Sales Invoice")
DEFAULT_PREFS = {
    "email_ticket_updates": 1, "portal_ticket_updates": 1, "email_message_alerts": 1,
    "portal_message_alerts": 1, "email_invoice_alerts": 0, "email_request_updates": 1,
}


def prefs(user: str) -> dict:
    row = frappe.db.get_value("Support Notification Preference", user, list(DEFAULT_PREFS), as_dict=True)
    return {k: cint(row.get(k)) if row else v for k, v in DEFAULT_PREFS.items()}


def _portal_user(user: str | None) -> bool:
    return bool(user and user not in ("Guest", "Administrator") and frappe.db.exists("User", user)
                and "Support Portal Customer" in frappe.get_roles(user))


def notify(user: str, subject: str, doctype: str, docname: str, *, portal_pref: str, email_pref: str | None = None,
           email_body: str | None = None):
    if not _portal_user(user) or user == frappe.session.user:
        return
    p = prefs(user)
    if p.get(portal_pref):
        try:
            frappe.get_doc({
                "doctype": "Notification Log",
                "for_user": user,
                "type": "Alert",
                "subject": subject,
                "document_type": doctype,
                "document_name": str(docname),
                "from_user": frappe.session.user if frappe.session.user != "Guest" else None,
            }).insert(ignore_permissions=True)
        except Exception:
            frappe.log_error(title="thinkNXG Support: portal notification failed")
    if email_pref and p.get(email_pref):
        frappe.sendmail(
            recipients=[frappe.db.get_value("User", user, "email") or user],
            subject=frappe.utils.strip_html(subject),
            message=(email_body or subject) + f'<p><a href="{frappe.utils.get_url(PORTAL_ROUTE)}">'
                                              f'{_("Open the support portal")}</a></p>',
            delayed=True,
        )


def _user_for_email(email: str | None) -> str | None:
    if not email:
        return None
    return frappe.db.get_value("User", {"email": email}) or (email if frappe.db.exists("User", email) else None)


def on_ticket_update(doc, method=None):
    if not doc.has_value_changed("status") or doc.is_new():
        return
    user = _user_for_email(doc.get("raised_by"))
    if not user:
        return
    subject = _("Ticket #{0} is now {1}").format(doc.name, doc.status)
    notify(user, subject, "HD Ticket", doc.name, portal_pref="portal_ticket_updates",
           email_pref="email_ticket_updates",
           email_body=f"<p>{frappe.utils.escape_html(subject)}: {frappe.utils.escape_html(doc.subject or '')}</p>")


def on_communication(doc, method=None):
    if doc.reference_doctype != "HD Ticket" or doc.communication_type != "Communication":
        return
    if doc.sent_or_received != "Sent":
        return
    raised_by = frappe.db.get_value("HD Ticket", doc.reference_name, "raised_by")
    user = _user_for_email(raised_by)
    if user:
        notify(user, _("New reply on ticket #{0}").format(doc.reference_name), "HD Ticket", doc.reference_name,
               portal_pref="portal_ticket_updates")


def notify_customer_message(conv, msg):
    if conv.get("is_guest"):
        from thinknxg_support.integrations.live_chat import email_guest_if_away

        email_guest_if_away(conv, msg)
        return
    notify(conv.started_by, _("New message: {0}").format(conv.subject), "Support Conversation Link", conv.name,
           portal_pref="portal_message_alerts", email_pref="email_message_alerts",
           email_body=_("<p>Support replied to your conversation <b>{0}</b>.</p>").format(
               frappe.utils.escape_html(conv.subject)))


def notify_agents(conv, msg):
    s = frappe.get_cached_doc("Support Portal Settings")
    users = [u.strip() for u in (s.raven_default_members or "").splitlines() if u.strip()]
    if conv.assigned_agent:
        users.append(conv.assigned_agent)
    if not users:
        users = frappe.get_all("Has Role", filters={"role": "Support Manager", "parenttype": "User"},
                               pluck="parent", limit=20)
    for user in dict.fromkeys(users):
        if user == frappe.session.user or not frappe.db.exists("User", user):
            continue
        try:
            frappe.get_doc({
                "doctype": "Notification Log", "for_user": user, "type": "Alert",
                "subject": (_("Live chat: {0}") if conv.get("conversation_type") == "Live Chat"
                            else _("Customer message: {0}")).format(conv.subject),
                "document_type": "Support Conversation Link", "document_name": conv.name,
            }).insert(ignore_permissions=True)
        except Exception:
            frappe.log_error(title="thinkNXG Support: agent notification failed")


def notify_request_update(req):
    notify(req.raised_by, _("Request {0} is now {1}").format(req.name, req.status), "Support Request", req.name,
           portal_pref="portal_ticket_updates", email_pref="email_request_updates")
