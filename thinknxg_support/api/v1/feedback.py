"""Feedback page reached from a link (WhatsApp, e-mail). The link's token is the only key; it opens one chat's survey."""
import frappe

from thinknxg_support import ratelimit
from thinknxg_support.integrations import feedback


@frappe.whitelist(allow_guest=True, methods=["GET"])
def form(conversation, token):
    ratelimit.check("feedback_form", 60, 600)
    conv = feedback.conv_from_link(conversation, token)
    cfg = feedback.survey_config()
    if not cfg:
        frappe.throw(frappe._("Feedback is not collected for chats."))
    agent = feedback._agent_of(conv)
    return {**cfg, "done": feedback.done(conv.name),
            "agent": (frappe.db.get_value("User", agent, "first_name") or "").strip() if agent else None}


@frappe.whitelist(allow_guest=True, methods=["POST"])
def submit(conversation, token, rating, resolved=None, comment=None):
    ratelimit.check("feedback_submit", 10, 600)
    conv = feedback.conv_from_link(conversation, token)
    return feedback.submit(conv, rating, resolved, comment, source="Feedback Link")
