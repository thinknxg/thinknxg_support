"""Customer feedback after a chat: one Support Chat Feedback per chat, tied to the chat and its agent."""
from __future__ import annotations

import hashlib
import secrets

import frappe
from frappe import _
from frappe.utils import add_to_date, cint, get_url, now_datetime, strip_html

CONV = "Support Conversation Link"
FB = "Support Chat Feedback"
LABELS = {5: 'Excellent', 4: 'Good', 3: 'Average', 2: 'Poor', 1: 'Very Poor'}
RESOLVED = ("Yes", "Partially", "No")


def _settings():
    return frappe.get_cached_doc("Support Portal Settings")


def mode() -> str:
    s = _settings()
    return (s.get("survey_mode") or "Optional") if frappe.db.exists("DocType", FB) else "Off"


def survey_config() -> dict | None:
    """What the chat widget and the feedback page show. None when the survey is off."""
    if mode() == "Off":
        return None
    s = _settings()
    return {
        "required": mode() == "Required",
        "title": s.get("survey_title") or _("Support Experience Feedback"),
        "intro": s.get("survey_intro") or _("Please rate your experience with our support agent."),
        "ask_resolution": cint(s.get("survey_ask_resolution")) if s.get("survey_ask_resolution") is not None else 1,
        "ask_comment": cint(s.get("survey_ask_comment")) if s.get("survey_ask_comment") is not None else 1,
        "comment_required_at": cint(s.get("survey_comment_required_at")),
        "labels": {str(k): _(v) for k, v in LABELS.items()},
    }


def done(conv_name: str) -> bool:
    return bool(frappe.db.exists(FB, {"conversation": conv_name}))


def _agent_of(conv) -> str | None:
    if conv.get("assigned_agent"):
        return conv.assigned_agent
    return frappe.db.get_value("Support Chat Assignment", {"conversation": conv.name}, "agent", order_by="creation desc")


def submit(conv, rating, resolved: str | None = None, comment: str | None = None, source: str = "Chat Widget") -> dict:
    """Save the customer's feedback for this chat (they may change it within a day), close the chat if still open,
    and tell the right people."""
    cfg = survey_config()
    if not cfg:
        frappe.throw(_("Feedback is not collected for chats."))
    rating = cint(rating)
    if rating < 1 or rating > 5:
        frappe.throw(_("Choose from 1 to 5 stars."))
    resolved = (resolved or "").strip() or None
    if resolved and resolved not in RESOLVED:
        frappe.throw(_("Unknown answer."))
    if cfg["ask_resolution"] and not resolved:
        frappe.throw(_("Tell us whether your issue was resolved."))
    comment = strip_html(comment or "").strip()[:2000] or None
    if cfg["ask_comment"] and cfg["comment_required_at"] and rating <= cfg["comment_required_at"] and not comment:
        frappe.throw(_("Please tell us what went wrong so we can improve."))
    existing = frappe.db.get_value(FB, {"conversation": conv.name}, ["name", "submitted_on"], as_dict=True)
    if existing and existing.submitted_on and existing.submitted_on < add_to_date(now_datetime(), days=-1):
        frappe.throw(_("Feedback for this chat can no longer be changed."))
    sentiment = "Positive" if rating >= 4 and resolved != "No" else (
        "Negative" if rating <= negative_at() or resolved == "No" else "Neutral")
    agent = _agent_of(conv)
    values = {
        "conversation": conv.name, "agent": agent, "rating": rating, "rating_label": _(LABELS[rating]),
        "resolved": resolved, "comment": comment, "sentiment": sentiment, "submitted_on": now_datetime(),
        "channel": conv.get("channel"), "queue": conv.get("queue"), "customer": conv.get("customer"),
        "customer_name": (frappe.db.get_value("Customer", conv.customer, "customer_name") if conv.get("customer") else None)
        or conv.get("guest_name") or conv.get("whatsapp_profile_name") or conv.get("guest_email") or _("Visitor"),
        "chat_closed_on": conv.get("closed_on") or conv.get("resolved_at"), "closure_reason": conv.get("closure_reason"),
        "handled_by_assistant": 0 if agent else 1, "source": source,
    }
    if existing:
        doc = frappe.get_doc(FB, existing.name)
        before = doc.sentiment
        doc.update(values)
        doc.save(ignore_permissions=True)
    else:
        before = None
        doc = frappe.get_doc({"doctype": FB, **values}).insert(ignore_permissions=True)
    frappe.db.set_value(CONV, conv.name, {"chat_rating": rating / 5.0, "feedback": doc.name}, update_modified=False)
    if conv.status != "Closed":
        from thinknxg_support.integrations import live_chat

        live_chat._close(frappe.get_doc(CONV, conv.name))
    if sentiment != before:
        notify(doc)
    from thinknxg_support.audit import log_event

    log_event("Feedback", reference_doctype=CONV, reference_name=conv.name,
              details={"rating": rating, "resolved": resolved, "agent": agent}, user="Administrator")
    return {"ok": True, "name": doc.name}


def negative_at() -> int:
    return cint(_settings().get("negative_feedback_at")) or 2


def notify(doc):
    """Negative: alert supervisors (and the agent if switched on). Positive: thank the agent."""
    from thinknxg_support.integrations import alerts

    s = _settings()
    stars = "★" * cint(doc.rating) + "☆" * (5 - cint(doc.rating))
    lines = [f"{stars} {doc.rating_label}" + (f" · {_('Resolved')}: {_(doc.resolved)}" if doc.resolved else ""),
             f"{_('Agent')}: {frappe.utils.get_fullname(doc.agent) if doc.agent else _('Assistant only')}"]
    route = f"support-chat-feedback/{doc.name}"
    if doc.sentiment == "Negative":
        roles = [r.strip() for r in (s.get("negative_feedback_roles") or "Support Manager").splitlines() if r.strip()]
        users = frappe.get_all("Has Role", filters={"role": ["in", roles], "parenttype": "User"}, pluck="parent", distinct=True)
        if doc.agent and cint(s.get("notify_agent_negative")):
            users.append(doc.agent)
        alerts.raise_alert("Negative Feedback", users, _("Negative feedback from {0}").format(doc.customer_name),
                           doc.comment or "", reference_doctype=doc.doctype, reference_name=doc.name, route=route,
                           group_key=f"csat:{doc.name}", lines=lines)
        if cint(s.get("email_negative_feedback")):
            emails = [e for e in (frappe.db.get_value("User", u, "email") for u in set(users)) if e]
            if emails:
                esc = frappe.utils.escape_html
                frappe.sendmail(recipients=emails, subject=_("Negative chat feedback: {0} ({1}/5)").format(doc.customer_name, doc.rating),
                                message="".join(f"<p>{esc(x)}</p>" for x in [*lines, doc.comment or ""]) +
                                f'<p><a href="{get_url("/app/" + route)}">{esc(_("Open the feedback"))}</a></p>',
                                reference_doctype=doc.doctype, reference_name=doc.name)
    elif doc.sentiment == "Positive" and doc.agent and cint(s.get("notify_agent_positive") if s.get("notify_agent_positive") is not None else 1):
        alerts.raise_alert("Positive Feedback", [doc.agent], _("{0} rated your chat {1}/5").format(doc.customer_name, doc.rating),
                           doc.comment or "", reference_doctype=doc.doctype, reference_name=doc.name, route=route,
                           group_key=f"csat:{doc.name}", lines=lines[:1])


# ------------------------------------------------------------------ asking for it
def _hash(token: str) -> str:
    return hashlib.sha256((token or "").encode()).hexdigest()


def feedback_link(conv) -> str:
    """A one-chat link to the feedback page (for WhatsApp and e-mail). Valid for 3 days."""
    token = secrets.token_urlsafe(24)
    frappe.db.set_value(CONV, conv.name, {"survey_token_hash": _hash(token), "survey_sent_on": now_datetime()},
                        update_modified=False)
    from thinknxg_support.constants import PORTAL_ROUTE

    return get_url(f"{PORTAL_ROUTE}/feedback?c={conv.name}&t={token}")


def conv_from_link(conversation: str, token: str):
    row = frappe.db.get_value(CONV, conversation, ["name", "survey_token_hash", "survey_sent_on"], as_dict=True) \
        if conversation and token else None
    import hmac

    if not (row and row.survey_token_hash and hmac.compare_digest(row.survey_token_hash, _hash(token))
            and row.survey_sent_on and row.survey_sent_on > add_to_date(now_datetime(), days=-3)):
        raise frappe.PermissionError(_("This feedback link has expired."))
    return frappe.get_doc(CONV, row.name)


def on_chat_closed(conv):
    """Ask automatically: the chat widget shows the survey by itself; WhatsApp chats get a link."""
    try:
        if mode() == "Off" or done(conv.name):
            return
        s = _settings()
        if conv.get("channel") == "WhatsApp" and cint(s.get("survey_whatsapp")):
            from thinknxg_support.integrations import conversations

            text = (s.get("survey_whatsapp_message") or _("How did we do? Please rate this chat: {link}"))
            conversations.post_agent_message(conv, "<p>" + frappe.utils.escape_html(text.replace("{link}", feedback_link(conv))) + "</p>",
                                             sender="Administrator", source="system", sender_type="System",
                                             response_source="Feedback request")
    except Exception:
        frappe.log_error(title="thinkNXG Support: feedback request failed")


def pending_for_guest(conv) -> bool:
    """Required mode: a closed chat that still owes its survey (last 24 hours)."""
    return bool(mode() == "Required" and conv.status == "Closed" and not done(conv.name)
                and (conv.get("closed_on") or conv.get("modified")) and
                frappe.utils.get_datetime(conv.get("closed_on") or conv.get("modified")) > add_to_date(now_datetime(), days=-1))


# ------------------------------------------------------------------ who may read feedback
def permission_query_conditions(user=None):
    """Supervisors see all feedback; agents see the feedback about their own chats."""
    user = user or frappe.session.user
    if {"Support Manager", "Support Portal Administrator", "System Manager"} & set(frappe.get_roles(user)):
        return ""
    return f"`tab{FB}`.agent = {frappe.db.escape(user)}"


def has_permission(doc, ptype=None, user=None):
    user = user or frappe.session.user
    if {"Support Manager", "Support Portal Administrator", "System Manager"} & set(frappe.get_roles(user)):
        return None
    return doc.agent == user and ptype in (None, "read", "print", "email", "report", "export")
