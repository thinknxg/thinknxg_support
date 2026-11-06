"""Chat console tools: canned responses and the end-of-chat wrap-up."""
from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, now_datetime, strip_html

CANNED = "Support Canned Response"
CONV = "Support Conversation Link"
STAFF = ["Support Agent", "Support Manager", "Support Portal Administrator", "System Manager"]


def permission_query_conditions(user=None):
    """Agents see the team's canned responses and their own private ones."""
    user = user or frappe.session.user
    if {"Support Manager", "Support Portal Administrator", "System Manager"} & set(frappe.get_roles(user)):
        return ""
    return f"(`tabSupport Canned Response`.visibility = 'Team' or `tabSupport Canned Response`.owner = {frappe.db.escape(user)})"


def has_permission(doc, ptype=None, user=None):
    user = user or frappe.session.user
    # Frappe v16 treats a falsy hook result (None included) as "deny": True defers to role permissions
    if {"Support Manager", "Support Portal Administrator", "System Manager"} & set(frappe.get_roles(user)):
        return True
    others = bool(doc.owner and doc.owner != user)  # a new record has no owner yet: it becomes the creator's
    if others and doc.visibility == "Only Me":
        return False  # someone else's private response
    if others and ptype in ("write", "delete", "cancel", "submit", "amend"):
        return False  # agents change only their own responses
    return True


@frappe.whitelist(methods=["GET"])
def canned_responses(channel: str | None = None):
    frappe.only_for(STAFF)
    rows = frappe.get_list(CANNED, filters={"enabled": 1}, fields=["name", "title", "shortcut", "category", "content",
                                                                    "channel", "language", "usage_count", "visibility"],
                           order_by="usage_count desc, title asc", limit=1000)
    out = [r for r in rows if not channel or r.channel in (None, "", "All Channels", channel)]
    # Helpdesk's own canned responses, read-only, when Helpdesk is installed
    if frappe.db.exists("DocType", "HD Canned Response"):
        try:
            for r in frappe.get_list("HD Canned Response", fields=["name", "title", "message"], limit=500):
                out.append({"name": "hd:" + r.name, "title": r.title, "shortcut": None, "category": _("Helpdesk"),
                            "content": r.message, "channel": "All Channels", "usage_count": 0, "visibility": "Team"})
        except frappe.PermissionError:
            pass
    return out


@frappe.whitelist(methods=["POST"])
def canned_used(name: str):
    frappe.only_for(STAFF)
    if name and not name.startswith("hd:") and frappe.db.exists(CANNED, name):
        frappe.db.sql(f"update `tab{CANNED}` set usage_count = coalesce(usage_count, 0) + 1, last_used_on = %s where name = %s",
                      (now_datetime(), name))
    return True


def _settings():
    return frappe.get_cached_doc("Support Portal Settings")


@frappe.whitelist(methods=["GET"])
def closing_form():
    """Reasons and wrap-up questions for the End chat dialog."""
    frappe.only_for(STAFF)
    s = _settings()
    reasons = [r.strip() for r in (s.get("closure_reasons") or "").splitlines() if r.strip()]
    questions = [{"idx": q.idx, "question": q.question, "answer_type": q.answer_type, "required": cint(q.required),
                  "options": [o.strip() for o in (q.options or "").splitlines() if o.strip()]}
                 for q in (s.get("wrap_up_questions") or []) if q.enabled]
    return {"reasons": reasons, "require_reason": cint(s.get("require_closure_reason")), "questions": questions,
            "closing_message": s.get("chat_closing_message") or ""}


@frappe.whitelist(methods=["POST"])
def end_chat(name: str, reason: str | None = None, notes: str | None = None, answers=None, send_closing_message=1):
    """Close a chat with a reason, wrap-up answers and notes. They are saved on the conversation and added to its
    history as an internal note; the customer sees only the optional closing message."""
    frappe.only_for(STAFF)
    conv = frappe.get_doc(CONV, name)
    conv.check_permission("write")
    form = closing_form()
    reason = (reason or "").strip()
    if form["require_reason"] and not reason:
        frappe.throw(_("Choose why the chat is ending."))
    if reason and form["reasons"] and reason not in form["reasons"]:
        frappe.throw(_("Unknown reason."))
    answers = frappe.parse_json(answers) if isinstance(answers, str) else (answers or {})
    rows = []
    for q in form["questions"]:
        a = answers.get(str(q["idx"])) if isinstance(answers, dict) else None
        a = strip_html(str(a)).strip()[:1000] if a not in (None, "") else ""
        if q["required"] and not a:
            frappe.throw(_("Answer: {0}").format(q["question"]))
        if q["answer_type"] == "Choice" and a and q["options"] and a not in q["options"]:
            frappe.throw(_("Pick one of the options for: {0}").format(q["question"]))
        if a:
            rows.append({"question": q["question"], "answer": a})
    notes = strip_html(notes or "").strip()[:4000]

    from thinknxg_support.integrations import conversations, realtime, routing

    if cint(send_closing_message) and form["closing_message"] and conv.status != "Closed" and not (
            conv.get("channel") == "Live Chat" and conv.get("is_guest") and conv.status == "Closed"):
        conversations.post_agent_message(conv, f"<p>{frappe.utils.escape_html(form['closing_message'])}</p>",
                                         sender="Administrator", source="system", sender_type="System",
                                         response_source="Chat closed")
    esc = frappe.utils.escape_html
    summary = [f"<p><b>{esc(_('Chat ended by {0}').format(frappe.utils.get_fullname(frappe.session.user)))}</b></p>"]
    if reason:
        summary.append(f"<p>{esc(_('Reason'))}: {esc(reason)}</p>")
    if rows:
        summary.append("<ul>" + "".join(f"<li>{esc(r['question'])}: <b>{esc(r['answer'])}</b></li>" for r in rows) + "</ul>")
    if notes:
        summary.append(f"<p>{esc(_('Notes'))}: {esc(notes)}</p>")
    conversations.post_agent_message(conv, "".join(summary), internal=1, sender=frappe.session.user, source="desk",
                                     sender_type="System", response_source="Chat wrap-up")
    conv.reload()
    conv.set("wrap_up_answers", [])
    for r in rows:
        conv.append("wrap_up_answers", r)
    conv.closure_reason = reason or None
    conv.closure_notes = notes or None
    conv.closed_by = frappe.session.user
    conv.closed_on = now_datetime()
    was_open = conv.status != "Closed"
    conv.status = "Closed"
    conv.flags.ignore_permissions = True
    conv.save()
    if was_open:
        routing.on_closed(conv)
    from thinknxg_support.integrations import escalations

    esc_doc = escalations.open_for(CONV, name) if escalations.enabled() else None
    if esc_doc:
        esc_doc.append("notes", {"note": _("Chat ended: {0}").format(reason or "-") + (f". {notes}" if notes else ""),
                                 "by_user": frappe.session.user, "noted_on": now_datetime()})
        esc_doc.save(ignore_permissions=True)
    realtime.bump(name)
    conversations.publish_agent_event(conv, "status")
    return {"ok": True}
