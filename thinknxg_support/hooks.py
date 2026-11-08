app_name = "thinknxg_support"
app_title = "thinkNXG Support"
app_publisher = "Kreatao"
app_description = "Unified customer service portal for thinkNXG ERP: Helpdesk tickets, Raven messaging and ERPNext self-service"
app_email = "support@thinknxg.com"
app_license = "mit"

# ERPNext is required because portal identity resolves to ERPNext Customer.
# Helpdesk and Raven are OPTIONAL and detected at runtime.
required_apps = ["erpnext"]

add_to_apps_screen = [
    {
        "name": "thinknxg_support",
        "logo": "/assets/thinknxg_support/images/logo.svg",
        "title": "thinkNXG Support",
        "route": "/thinkdesk",
    }
]

after_install = "thinknxg_support.install.after_install"
after_migrate = "thinknxg_support.install.after_migrate"
before_uninstall = "thinknxg_support.install.before_uninstall"

# Live chat launcher on public website pages (checks settings at runtime and stays hidden when disabled)
web_include_js = ["support_chat.bundle.js"]

# Desk: the support alert centre (pop-ups and sounds for chats, tickets, conversations, escalations) on every page,
# and the "Escalate" action on tickets, chats and requests
app_include_js = ["/assets/thinknxg_support/js/alert_center.js", "/assets/thinknxg_support/js/escalate_button.js"]

# Agents see the team's canned responses and their own private ones
permission_query_conditions = {
    "Support Canned Response": "thinknxg_support.integrations.agent_tools.permission_query_conditions",
    "Support Chat Feedback": "thinknxg_support.integrations.feedback.permission_query_conditions",
}
has_permission = {
    "Support Canned Response": "thinknxg_support.integrations.agent_tools.has_permission",
    "Support Chat Feedback": "thinknxg_support.integrations.feedback.has_permission",
}
web_include_css = ["support_chat.bundle.css"]

# Portal lives at /thinkdesk. ERPNext ships its own /support page, which is left untouched.
# The www files use app-specific names so they never collide with another app's www/support.
website_route_rules = [
    # guest-accessible full-page chat must precede the authenticated catch-all
    {"from_route": "/thinkdesk/chat", "to_route": "thinknxg_support_chat"},
    {"from_route": "/thinkdesk", "to_route": "thinknxg_support_portal"},
    {"from_route": "/thinkdesk/<path:app_path>", "to_route": "thinknxg_support_portal"},
]

doc_events = {
    # Helpdesk (optional) - events only fire when the DocType exists
    "HD Ticket": {
        "on_update": [
            "thinknxg_support.integrations.notifications.on_ticket_update",
            "thinknxg_support.integrations.escalations.on_hd_ticket",
            "thinknxg_support.integrations.alerts.on_hd_ticket",
        ],
        "after_insert": [
            "thinknxg_support.integrations.escalations.on_hd_ticket",
            "thinknxg_support.integrations.alerts.on_hd_ticket",
        ],
    },
    "Communication": {
        "after_insert": [
            "thinknxg_support.integrations.notifications.on_communication",
            "thinknxg_support.integrations.escalations.on_communication",
            "thinknxg_support.integrations.alerts.on_communication",
        ],
    },
    "Support Request": {
        "on_update": "thinknxg_support.integrations.escalations.on_support_request_update",
    },
    # every Customer is also an HD Customer (Helpdesk), with its contacts
    "Customer": {
        "on_update": "thinknxg_support.integrations.helpdesk.on_customer_change",  # also runs on insert
    },
    "Contact": {
        "on_update": "thinknxg_support.integrations.helpdesk.on_contact_change",
    },
    # Raven (optional)
    "Raven Message": {
        "after_insert": "thinknxg_support.integrations.raven.on_raven_message",
    },
    # Knowledge index for the AI assistant (Helpdesk optional)
    "HD Article": {
        "on_update": "thinknxg_support.integrations.ai.retrieval.on_article_change",
        "on_trash": "thinknxg_support.integrations.ai.retrieval.on_article_change",
    },
    "User": {
        "on_trash": "thinknxg_support.security.on_user_trash",
    },
}

scheduler_events = {
    "cron": {
        # overdue escalations: flag and alert
        "*/5 * * * *": ["thinknxg_support.integrations.escalations.check_overdue",
                        "thinknxg_support.integrations.automation.check_quiet"],
    },
    "hourly": [
        "thinknxg_support.integrations.alerts.expire_and_purge",
        "thinknxg_support.tasks.retry_failed_deliveries",
        "thinknxg_support.integrations.live_chat.close_idle_chats",
        "thinknxg_support.integrations.whatsapp.retry_failed",
    ],
    "daily": [
        "thinknxg_support.tasks.expire_access_and_grants",
        "thinknxg_support.tasks.purge_old_events",
        "thinknxg_support.integrations.live_chat.purge_guest_chats",
        "thinknxg_support.integrations.ai.housekeeping.purge_usage_logs",
    ],
    "daily_long": [
        "thinknxg_support.integrations.ai.retrieval.daily_refresh",
        "thinknxg_support.integrations.ai.crawler.scheduled",
    ],
}

fixtures = [
    {"dt": "Role", "filters": [["name", "like", "Support %"]]},
]

ignore_links_on_delete = ["Support Portal Event"]

export_python_type_annotations = True
