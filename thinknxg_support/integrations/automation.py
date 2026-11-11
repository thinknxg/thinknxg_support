"""Automation rules (Support Automation Rule).

* Visitor on a Page: the website chat shows the rule's message after the visitor has been on a matching page for
  the set seconds (worked out in the browser; nothing is stored until the visitor answers).
* Customer Quiet: every five minutes, open chats where our last reply has had no answer for the set minutes: send a
  nudge, close the chat (as the idle close does), or notify / escalate. Once per quiet spell.
* Chat Closed Needing Follow-up: when a chat ends with "follow-up needed: Yes": a to-do for the agent, or an
  escalation.
* New Chat Outside Chat Hours: instead of the standard offline message, send the rule's message or collect the
  visitor's details for a lead.
Every run is logged (Support Automation Run) and counted on the rule.
"""
from __future__ import annotations

import fnmatch

import frappe
from frappe import _
from frappe.utils import add_days, add_to_date, cint, now_datetime, nowdate

RULE = "Support Automation Rule"
RUN = "Support Automation Run"
CONV = "Support Conversation Link"
MSG = "Support Portal Message"
CHANNEL = {"Live Chat": "channel_live_chat", "WhatsApp": "channel_whatsapp", "Portal": "channel_portal"}


def rules(trigger: str) -> list:
    if not frappe.db.exists("DocType", RULE):
        return []
    names = frappe.get_all(RULE, filters={"enabled": 1, "trigger": trigger}, pluck="name", order_by="creation asc")
    return [frappe.get_cached_doc(RULE, n) for n in names]


def applies(rule, conv) -> bool:
    field = CHANNEL.get(conv.get("channel") or "Portal")
    if not field or not cint(rule.get(field)):
        return False
    return not rule.queue or rule.queue == conv.get("queue")


def _ran(rule, conv, since=None) -> bool:
    f = {"rule": rule.name, "conversation": conv.name}
    if since:
        f["ran_on"] = [">", since]
    return bool(frappe.db.exists(RUN, f))


def _log(rule, conv, result: str):
    frappe.get_doc({"doctype": RUN, "rule": rule.name, "conversation": conv.name, "action": rule.action,
                    "ran_on": now_datetime(), "result": result[:500]}).insert(ignore_permissions=True)
    frappe.db.set_value(RULE, rule.name, {"runs": cint(rule.runs) + 1, "last_run_on": now_datetime()},
                        update_modified=False)
    frappe.clear_document_cache(RULE, rule.name)


def _message(conv, rule):
    from thinknxg_support.integrations.ai import engine, language

    text = language.localize(conv, rule.message or "")
    engine.post(conv, "".join(f"<p>{frappe.utils.escape_html(p)}</p>" for p in text.split("\n\n") if p.strip()),
                "Bot", f"Automation: {rule.name}")


def _template(conv, rule) -> str:
    """1.17: an approved WhatsApp template, with the 24-hour window open or closed. Never sends marketing to a number
    that has not opted in, and never guesses a variable."""
    from thinknxg_support.integrations import wa_templates, whatsapp

    if conv.get("channel") != "WhatsApp":
        return "skipped: not a WhatsApp chat"
    if cint(rule.text_when_window_open) and (rule.message or "").strip() and whatsapp.window_open(conv):
        _message(conv, rule)
        return "message sent (window open)"
    try:
        wa_templates.send(conv, rule.whatsapp_template, user=None, source="system", automatic=rule.name,
                          keep_status=conv.get("status") == "Closed")
    except wa_templates.OptInRequired as e:
        return f"skipped: {e}"[:300]
    except wa_templates.TemplateError as e:
        return f"skipped: {e}"[:300]
    return "template sent"


def _escalate(conv, rule, why: str):
    from thinknxg_support.integrations import escalations

    query_type = "Support Chat" if conv.get("channel") in ("Live Chat", "WhatsApp") else "Conversation"
    return escalations.raise_escalation(query_type, "Automation Rule", CONV, conv.name,
                                        subject=conv.subject or why, assigned_to=conv.get("assigned_agent"),
                                        team=conv.get("queue"), priority=rule.escalation_priority or "Medium",
                                        note=f"{rule.name}: {why}", user="Administrator", **escalations._conv_details(conv))


def run(rule, conv, why: str = "") -> str:
    """Do the rule's action for this chat (callers check the trigger). Returns what happened."""
    a = rule.action
    if a == "Send Message":
        _message(conv, rule)
        result = "message sent"
    elif a == "Send WhatsApp Template":
        result = _template(conv, rule)
    elif a == "Collect Details":
        from thinknxg_support.integrations import lead_capture

        result = "collecting details" if lead_capture.start(conv, intro=rule.message or None, source="automation") \
            else "not started (already a lead, or leads are off)"
    elif a == "Close Chat":
        from thinknxg_support.integrations import live_chat

        if rule.message:
            _message(conv, rule)
        live_chat._close(frappe.get_doc(CONV, conv.name))
        result = "chat closed"
    elif a == "Create Follow-up Task":
        user = conv.get("closed_by") or conv.get("assigned_agent")
        if not user or user in ("Guest", "Administrator"):
            user = None
        if user:
            frappe.get_doc({"doctype": "ToDo", "allocated_to": user, "reference_type": CONV, "reference_name": conv.name,
                            "date": add_days(nowdate(), cint(rule.task_days)), "priority": "Medium", "status": "Open",
                            "assigned_by": "Administrator",
                            "description": rule.message or _("Follow up with the customer from chat {0}.").format(conv.name),
                            }).insert(ignore_permissions=True)
            result = f"to-do for {user}"
        else:
            result = "no agent to give the to-do to"
    elif a == "Notify or Escalate":
        esc = _escalate(conv, rule, why or rule.name)
        result = f"escalation {esc.name}" if esc else "escalations are switched off"
    else:
        result = "unknown action"
    _log(rule, conv, result)
    return result


# ------------------------------------------------------------------ triggers
def page_rules() -> list[dict]:
    """For the website chat: messages to show on matching pages after N seconds."""
    return [{"rule": r.name, "pattern": (r.page_pattern or "").strip(), "seconds": cint(r.seconds_on_page) or 20,
             "message": r.message} for r in rules("Visitor on a Page") if cint(r.channel_live_chat) and r.message]


def page_matches(pattern: str, path: str) -> bool:
    pattern = (pattern or "").strip()
    return not pattern or fnmatch.fnmatch(path or "/", pattern) or (path or "").rstrip("/") == pattern.rstrip("/")


def check_quiet():
    """Scheduler (every 5 minutes)."""
    rs = rules("Customer Quiet")
    if not rs:
        return
    shortest = min(cint(r.quiet_minutes) or 10 for r in rs)
    cut = add_to_date(now_datetime(), minutes=-shortest)
    convs = frappe.get_all(CONV, filters={"status": ["!=", "Closed"], "last_activity_at": ["<", cut]},
                           fields=["name"], order_by="last_activity_at desc", limit=300)
    for c in convs:
        try:
            _quiet(frappe.get_doc(CONV, c.name), rs)
            frappe.db.commit()
        except Exception:
            frappe.db.rollback()
            frappe.log_error(title="thinkNXG Support: automation rule failed")


def _quiet(conv, rs):
    last = frappe.get_all(MSG, filters={"conversation": conv.name, "is_internal": 0},
                          fields=["direction", "creation"], order_by="creation desc", limit=1)
    if not last or last[0].direction != "Outbound":
        return  # waiting for us, not for the customer
    last_inbound = frappe.db.get_value(MSG, {"conversation": conv.name, "direction": "Inbound"}, "creation",
                                       order_by="creation desc")
    for rule in rs:
        if not applies(rule, conv):
            continue
        if last[0].creation > add_to_date(now_datetime(), minutes=-(cint(rule.quiet_minutes) or 10)):
            continue
        if _ran(rule, conv, since=last_inbound):
            continue  # once per quiet spell
        run(rule, conv, _("The customer has not replied for {0} minutes.").format(rule.quiet_minutes))
        if rule.action == "Close Chat":
            return


def on_closed(conv):
    conv = frappe.get_doc(CONV, conv.name)
    if conv.get("needs_follow_up") != "Yes":
        return
    for rule in rules("Chat Closed Needing Follow-up"):
        if applies(rule, conv) and not _ran(rule, conv):
            run(rule, conv, _("The chat ended with a follow-up needed."))


def outside_hours(conv) -> bool:
    """A new chat outside chat hours: True when a rule answered it (the standard offline message is then not sent)."""
    handled = False
    for rule in rules("New Chat Outside Chat Hours"):
        if applies(rule, conv) and not _ran(rule, conv):
            run(rule, conv, _("Outside chat hours."))
            handled = True
            break
    return handled
