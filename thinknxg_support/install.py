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
