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
        "on_update": "thinknxg_support.integrations.notifications.on_ticket_update",
    },
    "Communication": {
        "after_insert": "thinknxg_support.integrations.notifications.on_communication",
    },
    # Raven (optional)
    "Raven Message": {
        "after_insert": "thinknxg_support.integrations.raven.on_raven_message",
    },
    "User": {
        "on_trash": "thinknxg_support.security.on_user_trash",
    },
}

scheduler_events = {
    "hourly": [
        "thinknxg_support.tasks.retry_failed_deliveries",
        "thinknxg_support.integrations.live_chat.close_idle_chats",
        "thinknxg_support.integrations.whatsapp.retry_failed",
    ],
    "daily": [
        "thinknxg_support.tasks.expire_access_and_grants",
        "thinknxg_support.tasks.purge_old_events",
        "thinknxg_support.integrations.live_chat.purge_guest_chats",
    ],
}

fixtures = [
    {"dt": "Role", "filters": [["name", "like", "Support %"]]},
]

ignore_links_on_delete = ["Support Portal Event"]

export_python_type_annotations = True
