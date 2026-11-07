"""Install / migrate / uninstall lifecycle for thinkNXG Support."""
import frappe

PORTAL_ROLES = {
    # role: desk_access
    "Support Portal Customer": 0,
    "Support Organization Manager": 0,
    "Support Billing Contact": 0,
    "Support Agent": 1,
    "Support Manager": 1,
    "Support Portal Administrator": 1,
}


def after_install():
    ensure_roles()
    ensure_defaults()
    ensure_ai_defaults()
    from thinknxg_support.landing import ensure_defaults as ensure_landing

    ensure_landing()
    ensure_kb_source()
    ensure_escalation_defaults()
    ensure_agent_tool_defaults()
    ensure_feedback_defaults()
    from thinknxg_support.integrations import capabilities

    capabilities.refresh(save=True)
    frappe.db.commit()


def after_migrate():
    ensure_roles()
    try:
        from thinknxg_support.integrations import capabilities

        capabilities.refresh(save=True)
    except Exception:
        frappe.log_error(title="thinkNXG Support: capability refresh failed")


def ensure_roles():
    for role, desk in PORTAL_ROLES.items():
        if frappe.db.exists("Role", role):
            continue
        frappe.get_doc(
            {"doctype": "Role", "role_name": role, "desk_access": desk, "is_custom": 0}
        ).insert(ignore_permissions=True)


def ensure_ai_defaults():
    """Assistant settings, a starter chatbot (disabled) and a default queue. Never overwrites existing records."""
    ai = frappe.get_single("Support AI Settings")
    defaults = {"assistant_name": "Assistant", "provider": "OpenAI Compatible", "api_base_url": "https://api.openai.com/v1",
                "embedding_base_url": "https://api.openai.com/v1", "temperature": 0.2, "max_output_tokens": 600,
                "timeout_seconds": 30, "top_k": 4, "min_relevance": 0.3, "chunk_size": 900, "max_ai_replies": 15,
                "handoff_on": "Low", "usage_retention_days": 90, "answer_guests": 1, "answer_customers": 1,
                "channel_live_chat": 1, "only_answer_from_kb": 1, "show_sources": 1, "suggest_follow_ups": 1,
                "index_helpdesk_articles": 1, "index_snippets": 1, "redact_contact_details": 1,
                "disclaimer": "Answers are written by AI from our help articles and can be wrong.",
                "no_answer_message": "I couldn't find that in our help articles, so I'm passing you to a member of our team."}
    if not ai.assistant_name:
        ai.update(defaults)
        ai.flags.ignore_permissions = True
        ai.flags.ignore_mandatory = True
        ai.save()
    if not frappe.db.exists("Support Chatbot", "Starter Bot"):
        frappe.get_doc({
            "doctype": "Support Chatbot", "bot_name": "Starter Bot", "enabled": 0, "display_name": "Assistant",
            "channel_live_chat": 1,
            "welcome_message": "Hi! I can help with common questions, or connect you with our team.",
            "welcome_buttons": "Opening hours | opening-hours\nTrack an order | track-order\nTalk to a person | @agent",
            "fallback_action": "Ask AI, Then Hand Off",
            "fallback_message": "Let me connect you with someone from our team.",
            "handoff_keywords": "agent, human, person, representative, someone, staff, موظف, شخص",
            "rules": [
                {"rule_name": "opening-hours", "enabled": 1, "priority": 10, "trigger_type": "Keywords",
                 "trigger": "opening hours, working hours, open today, office hours, ساعات العمل", "action": "Reply",
                 "response": "Our support team works Sunday to Thursday, 08:00 to 17:00 (Muscat time).",
                 "buttons": "Talk to a person | @agent"},
                {"rule_name": "track-order", "enabled": 1, "priority": 5, "trigger_type": "Keywords",
                 "trigger": "track order, order status, delivery status, where is my order", "action": "Reply",
                 "response": "Logged-in customers can see every order and its delivery progress under Orders & invoices in the portal.",
                 "buttons": "Ask another question | @ai\nTalk to a person | @agent"},
                {"rule_name": "complaint", "enabled": 1, "priority": 20, "trigger_type": "Keywords",
                 "trigger": "complaint, refund, cancel my, شكوى", "action": "Reply and Hand Off",
                 "response": "I'm sorry to hear that. I'm connecting you with a member of our team now."},
            ],
        }).insert(ignore_permissions=True)
    if not frappe.db.exists("Support Chat Queue", "General Support"):
        frappe.get_doc({"doctype": "Support Chat Queue", "queue_name": "General Support", "enabled": 1,
                        "assignment_rule": "Least Busy", "only_online_agents": 1, "channel_live_chat": 1,
                        "channel_whatsapp": 1, "channel_portal": 1}).insert(ignore_permissions=True)


def ensure_feedback_defaults():
    """Post-chat survey on (optional) for new sites; existing values are kept."""
    ps = frappe.get_single("Support Portal Settings")
    if not ps.meta.has_field("survey_mode") or ps.survey_mode:
        return
    ps.survey_mode = "Optional"
    ps.flags.ignore_permissions = True
    ps.flags.ignore_validate = True
    ps.save()


RESOLUTION_QUESTIONS = (("Issue Resolved", "Was the customer's issue resolved?"),
                        ("Follow-up Needed", "Does the customer need a follow-up?"))


def ensure_resolution_questions(ps) -> bool:
    """End chat always asks (Yes/No, required): was the issue resolved, does the customer need a follow-up.
    Existing questions with the same wording are reused; nothing else is changed."""
    if not frappe.get_meta("Support Chat Closing Question").has_field("report_as"):
        return False
    changed = False
    for key, text in RESOLUTION_QUESTIONS:
        row = next((q for q in ps.wrap_up_questions if q.get("report_as") == key), None) or next(
            (q for q in ps.wrap_up_questions if (q.question or "").strip().lower() == text.lower()), None)
        if row is None:
            ps.append("wrap_up_questions", {"question": text, "answer_type": "Yes/No", "required": 1, "enabled": 1,
                                            "report_as": key})
            changed = True
        elif (row.get("report_as"), row.answer_type, int(row.required or 0), int(row.enabled or 0)) != (key, "Yes/No", 1, 1):
            row.update({"report_as": key, "answer_type": "Yes/No", "required": 1, "enabled": 1})
            changed = True
    return changed


def ensure_agent_tool_defaults():
    """Alert rules per activity, chat closure reasons and wrap-up questions. Never overwrites existing values."""
    if frappe.db.exists("DocType", "Support Alert Settings"):
        from thinknxg_support.integrations.alerts import DEFAULTS

        s = frappe.get_single("Support Alert Settings")
        have = {r.kind for r in s.rules}
        for kind, d in DEFAULTS.items():
            if kind not in have:
                s.append("rules", {"kind": kind, "enabled": 1, "popup": 1, "sound": d["sound"], "volume": d["volume"],
                                   "repeat_until_ack": d["repeat_until_ack"], "repeat_seconds": d["repeat_seconds"] or 15,
                                   "max_repeats": d["max_repeats"], "desktop_notification": d["desktop_notification"]})
        s.flags.ignore_permissions = True
        s.save()
    ps = frappe.get_single("Support Portal Settings")
    changed = False
    if ps.meta.has_field("closure_reasons") and not ps.closure_reasons:
        ps.closure_reasons = "\n".join(["Resolved", "Answered with a help article", "Ticket created for follow-up",
                                        "Customer stopped responding", "Transferred to another channel", "Duplicate chat",
                                        "Spam or test", "Other"])
        changed = True
    if ps.meta.has_field("wrap_up_questions") and not ps.wrap_up_questions:
        for q, kind, opts, req in (("Was the customer's issue resolved?", "Yes/No", "", 1),
                                   ("Topic", "Choice", "Billing\nTechnical\nAccount and access\nOrders and delivery\nOther", 0),
                                   ("Does the customer need a follow-up?", "Yes/No", "", 1)):
            ps.append("wrap_up_questions", {"question": q, "answer_type": kind, "options": opts, "required": req, "enabled": 1})
        changed = True
    if ps.meta.has_field("wrap_up_questions") and ensure_resolution_questions(ps):
        changed = True
    if changed:
        ps.flags.ignore_permissions = True
        ps.flags.ignore_validate = True
        ps.save()


def ensure_escalation_defaults():
    """Escalation settings with response / resolution targets per priority. Never overwrites existing values."""
    if not frappe.db.exists("DocType", "Support Escalation Settings"):
        return
    s = frappe.get_single("Support Escalation Settings")
    if s.targets:
        return
    for priority, (resp, resol) in (("Critical", (15, 240)), ("High", (30, 480)), ("Medium", (120, 1440)),
                                    ("Low", (480, 4320))):
        s.append("targets", {"priority": priority, "response_minutes": resp, "resolution_minutes": resol})
    if not s.default_team and frappe.db.exists("Support Chat Queue", "General Support"):
        s.default_team = "General Support"
    s.flags.ignore_permissions = True
    s.save()


def ensure_kb_source():
    """A disabled starter source for the Frappe help centre, with the thinkNXG rebrand rules filled in.
    It stays disabled and unconfirmed until an administrator checks the licence and turns it on."""
    if not frappe.db.exists("DocType", "Support Knowledge Source") or frappe.db.exists("Support Knowledge Source", "Frappe Help Centre"):
        return
    from thinknxg_support.integrations.kb_import.rebrand import DEFAULT_LINK_RULES, DEFAULT_RULES

    doc = frappe.get_doc({"doctype": "Support Knowledge Source", "source_name": "Frappe Help Centre", "enabled": 0,
                          "source_type": "Frappe Helpdesk", "base_url": "https://support.frappe.io",
                          "help_center_url": "https://support.frappe.io/help",
                          "rules": [{"find": f, "replace_with": r, "match_case": 1, "enabled": 1} for f, r in DEFAULT_RULES],
                          "link_rules": [{"kind": k, "find": f, "replace_with": r, "keep_path": kp, "enabled": e}
                                         for k, f, r, kp, e in DEFAULT_LINK_RULES]})
    doc.insert(ignore_permissions=True)


def ensure_defaults():
    s = frappe.get_single("Support Portal Settings")
    changed = False
    defaults = {
        "portal_title": "thinkNXG Support",
        "primary_color": "#0F766E",
        "enable_tickets": 1,
        "enable_conversations": 1,
        "enable_knowledge": 1,
        "enable_services": 1,
        "enable_account": 1,
        "enable_documents": 1,
        "enable_helpdesk": 1,
        "enable_raven": 0,
        "raven_relay_mode": "Prefix Required",
        "raven_reply_prefix": "/r",
        "auto_create_helpdesk_customer": 1,
        "reopen_window_days": 7,
        "allowed_attachment_extensions": "pdf,png,jpg,jpeg,gif,webp,txt,csv,xlsx,docx,zip",
        "max_attachment_mb": 10,
        "max_attachments_per_message": 5,
        "message_rate_limit": 30,
        "ticket_rate_limit": 10,
        "require_contact_link": 1,
        "event_retention_days": 365,
        "default_language": "en",
        "enable_live_chat": 1,
        "allow_guest_chat": 1,
        "show_chat_on_website": 1,
        "chat_position": "Right",
        "chat_title": "Chat with support",
        "chat_greeting": "Hi! How can we help you today?",
        "chat_offline_message": "We're offline right now. Leave a message and we'll reply by email.",
        "chat_privacy_note": "We use your name and email only to answer this chat.",
        "chat_days": "Sun,Mon,Tue,Wed,Thu",
        "chat_start_time": "08:00:00",
        "chat_end_time": "17:00:00",
        "chat_auto_close_hours": 24,
        "guest_chat_rate_limit": 20,
        "guest_chat_retention_days": 365,
        "show_whatsapp_button": 1,
        "whatsapp_prefill_text": "Hello, I need help with",
        "whatsapp_api_version": "v22.0",
        "whatsapp_template_language": "en",
        "whatsapp_link_contacts": 1,
    }
    for key, value in defaults.items():
        if s.meta.has_field(key) and s.get(key) in (None, "", 0) and value not in (0, None):
            s.set(key, value)
            changed = True
    if changed:
        s.flags.ignore_permissions = True
        s.flags.ignore_mandatory = True
        s.save()


def before_uninstall():
    """Data is retained by Frappe's uninstall (DocTypes are dropped). Log the event."""
    frappe.logger("thinknxg_support").info("thinkNXG Support is being uninstalled")
    # Custom roles are left in place deliberately: removing them could strip
    # access from users that also use other apps. Remove manually if required.
