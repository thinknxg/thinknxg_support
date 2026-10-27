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
