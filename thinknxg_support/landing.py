"""Builds the landing page from Support Portal Settings. Everything returned here is safe for visitors:
published articles only, services open to all customers only, snippets for the viewer's audience only,
and every piece of HTML sanitised on the way out."""
from __future__ import annotations

import frappe
from frappe.utils import cint, get_time

from thinknxg_support.integrations import helpdesk, knowledge
from thinknxg_support.utils import clean_html, safe_link, settings

QUICK_ACTIONS = ("ticket", "chat", "knowledge", "my_tickets", "orders", "services", "whatsapp", "contact")
DEFAULT_ACTIONS = {"Visitors": ["chat", "knowledge", "ticket", "whatsapp"],
                   "Customers": ["ticket", "chat", "my_tickets", "orders", "services", "knowledge"]}
LOGIN_ONLY = {"ticket", "my_tickets", "orders", "services"}


def viewer_audience() -> tuple[str, object]:
    """Visitors (guests and logged-in users without portal access) or Customers."""
    if frappe.session.user == "Guest":
        return "Visitors", None
    from thinknxg_support.security import PortalAccessError, get_portal_user

    try:
        pu = get_portal_user()
    except (PortalAccessError, frappe.AuthenticationError):
        return "Visitors", None
    return "Customers", pu


def menu_links(audience: str | None = None) -> list[dict]:
    audience = audience or viewer_audience()[0]
    out = []
    for r in settings().get("menu_links") or []:
        if not r.enabled or r.audience not in ("Everyone", audience) or not safe_link(r.url):
            continue
        external = r.url.startswith(("http://", "https://")) and frappe.utils.get_url() not in r.url
        out.append({"label": r.label, "label_ar": r.label_ar or None, "url": r.url, "location": r.location or "Header",
                    "new_tab": bool(r.open_in_new_tab), "external": external})
    return out[:12]


def kb_open(audience: str) -> bool:
    s = settings()
    if not (s.enable_knowledge and knowledge.available()):
        return False
    return audience == "Customers" or bool(s.public_knowledge)


def _hours() -> dict:
    s = settings()
    from thinknxg_support.integrations.live_chat import is_online

    days = [d.strip()[:3].title() for d in (s.chat_days or "").split(",") if d.strip()]
    fmt = lambda t: get_time(t).strftime("%H:%M") if t else None  # noqa: E731
    return {"days": days, "start": fmt(s.chat_start_time), "end": fmt(s.chat_end_time), "online": is_online()}


def _faq(row, audience):
    lines = [x for x in (row.items or "").splitlines() if "|" in x]
    if lines:
        return [{"q": q.strip(), "a": clean_html(f"<p>{frappe.utils.escape_html(a.strip())}</p>")}
                for q, a in (x.split("|", 1) for x in lines)][: cint(row.item_limit) or 6]
    aud = ["Everyone", "Customers"] if audience == "Customers" else ["Everyone"]
    if not frappe.db.exists("DocType", "Support Knowledge Snippet"):
        return []
    rows = frappe.get_all("Support Knowledge Snippet", filters={"enabled": 1, "audience": ["in", aud]},
                          fields=["question", "answer"], order_by="modified desc", limit=cint(row.item_limit) or 6)
    return [{"q": r.question, "a": clean_html(r.answer or "", max_len=20000)} for r in rows]


def _cards(row):
    out = []
    for line in (row.items or "").splitlines():
        parts = [p.strip() for p in line.split("|")]
        if not parts or not parts[0]:
            continue
        link = parts[2] if len(parts) > 2 and safe_link(parts[2]) else None
        out.append({"title": parts[0][:80], "text": (parts[1] if len(parts) > 1 else "")[:300], "link": link})
    return out[:12]


def _services(limit):
    rows = frappe.get_all("Support Service", filters={"enabled": 1, "eligibility": "All Customers"},
                          fields=["name", "category", "description", "response_target"],
                          order_by="sort_order asc, service_name asc", limit=limit)
    return [dict(r) for r in rows]


def _actions(row, audience):
    s = settings()
    keys = [k.strip().lower() for k in (row.items or "").splitlines() if k.strip()] or DEFAULT_ACTIONS[audience]
    from thinknxg_support.integrations import live_chat

    whatsapp = live_chat.whatsapp_url()
    out = []
    for k in keys:
        if k not in QUICK_ACTIONS:
            continue
        if k == "ticket" and not (s.enable_tickets and helpdesk.available()):
            continue
        if k == "my_tickets" and (audience != "Customers" or not (s.enable_tickets and helpdesk.available())):
            continue
        if k == "chat" and not s.enable_live_chat:
            continue
        if k == "knowledge" and not kb_open(audience):
            continue
        if k == "orders" and (audience != "Customers" or not s.enable_account):
            continue
        if k == "services" and not s.enable_services:
            continue
        if k == "whatsapp" and not whatsapp:
            continue
        if k == "contact" and not (s.support_email or s.support_phone):
            continue
        out.append({"key": k, "login": k in LOGIN_ONLY and audience != "Customers",
                    "href": whatsapp if k == "whatsapp" else None})
    return out


def build() -> dict:
    s = settings()
    audience, pu = viewer_audience()
    audience_kb = "Customers" if audience == "Customers" else "Everyone"
    sections = []
    for row in s.get("landing_sections") or []:
        if not row.enabled or row.audience not in ("Everyone", audience):
            continue
        t = row.section_type
        sec = {"type": t, "title": row.title or None, "subtitle": row.subtitle or None, "style": row.style or "Plain",
               "image": row.image or None,
               "button": {"label": row.button_label, "link": row.button_link}
               if row.button_label and safe_link(row.button_link) else None}
        limit = min(cint(row.item_limit) or 6, 24)
        try:
            if t == "Hero":
                sec["search"] = bool(row.show_search) and kb_open(audience)
            elif t == "Quick Actions":
                sec["actions"] = _actions(row, audience)
                if not sec["actions"]:
                    continue
            elif t == "Popular Articles":
                if not kb_open(audience):
                    continue
                sec["articles"] = knowledge.search_articles(None, limit=limit, audience=audience_kb)
                if not sec["articles"]:
                    continue
            elif t == "Knowledge Categories":
                if not kb_open(audience):
                    continue
                sec["categories"] = knowledge.article_categories(audience=audience_kb)[:limit]
                if not sec["categories"]:
                    continue
            elif t == "Services":
                if not s.enable_services:
                    continue
                sec["services"] = _services(limit)
                if not sec["services"]:
                    continue
            elif t == "FAQ":
                sec["faq"] = _faq(row, audience)
                if not sec["faq"]:
                    continue
            elif t == "Contact and Hours":
                from thinknxg_support.integrations import live_chat

                sec["contact"] = {"email": s.support_email, "phone": s.support_phone, "whatsapp": live_chat.whatsapp_url(),
                                  "chat": bool(s.enable_live_chat), **_hours()}
            elif t in ("Announcement", "Custom Content"):
                sec["html"] = clean_html(row.content or "", max_len=50000)
                if not frappe.utils.strip_html(sec["html"]).strip():
                    continue
            elif t == "Cards":
                sec["cards"] = _cards(row)
                if not sec["cards"]:
                    continue
            elif t == "Account Summary":
                if audience != "Customers":
                    continue
        except Exception:
            frappe.log_error(title=f"thinkNXG Support: landing section {t} failed")
            continue
        sections.append(sec)
    return {"audience": audience, "sections": sections}


DEFAULT_SECTIONS = [
    {"section_type": "Hero", "audience": "Everyone", "style": "Brand", "title": "How can we help you today?",
     "subtitle": "Search our help articles, chat with our team, or raise a ticket. Support in English and Arabic.",
     "show_search": 1},
    {"section_type": "Quick Actions", "audience": "Everyone", "style": "Plain"},
    {"section_type": "Account Summary", "audience": "Customers", "style": "Plain"},
    {"section_type": "Popular Articles", "audience": "Everyone", "style": "Tinted", "item_limit": 6},
    {"section_type": "Services", "audience": "Everyone", "style": "Plain", "item_limit": 6},
    {"section_type": "FAQ", "audience": "Everyone", "style": "Tinted", "item_limit": 6},
    {"section_type": "Contact and Hours", "audience": "Everyone", "style": "Plain"},
    {"section_type": "Call to Action", "audience": "Visitors", "style": "Brand", "title": "Already a customer?",
     "subtitle": "Log in to raise tickets, follow their progress, and see your orders and invoices.",
     "button_label": "Log in", "button_link": "/login"},
]


def ensure_defaults():
    s = frappe.get_single("Support Portal Settings")
    changed = False
    if not s.get("landing_sections"):
        for row in DEFAULT_SECTIONS:
            s.append("landing_sections", {"enabled": 1, **row})
        changed = True
    if not s.get("menu_links"):
        s.append("menu_links", {"label": "Website", "label_ar": "الموقع", "url": "/", "location": "Header",
                                "audience": "Everyone", "open_in_new_tab": 0, "enabled": 1})
        changed = True
    if changed:
        s.flags.ignore_permissions = True
        s.flags.ignore_mandatory = True
        s.save()
