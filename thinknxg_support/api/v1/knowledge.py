from __future__ import annotations

import frappe
from frappe import _

from thinknxg_support import ratelimit
from thinknxg_support.integrations import knowledge
from thinknxg_support.security import PortalAccessError, get_portal_user
from thinknxg_support.utils import require_module, settings


def _viewer():
    """Customers always; visitors (guests or users without portal access) only with a public knowledge base."""
    require_module("knowledge")
    if frappe.session.user != "Guest":
        try:
            get_portal_user(allow_staff_without_grant=True)
            return
        except PortalAccessError:
            pass
    if not settings().public_knowledge:
        raise frappe.AuthenticationError(_("Please log in to read our help articles."))
    ratelimit.check("kb_public", 60, 60)


@frappe.whitelist(allow_guest=True, methods=["GET"])
def search(q=None, category=None, limit=10):
    _viewer()
    return knowledge.search_articles(q, category, limit)


@frappe.whitelist(allow_guest=True, methods=["GET"])
def article(name):
    _viewer()
    out = knowledge.get_article(name)
    out["my_vote"] = knowledge.my_vote(name)
    return out


@frappe.whitelist(allow_guest=True, methods=["GET"])
def sidebar():
    """Categories with their article titles, for the knowledge-base navigation."""
    _viewer()
    return knowledge.sidebar()


@frappe.whitelist(allow_guest=True, methods=["GET"])
def related(name, limit=5):
    _viewer()
    return knowledge.related(name, limit=limit)


@frappe.whitelist(allow_guest=True, methods=["POST"])
def feedback(name, vote, comment=None):
    """Thumbs up / down on an article; one vote per signed-in user or anonymous visitor, changeable."""
    _viewer()
    ratelimit.check("kb_feedback", 20, 600)
    customer = None
    if frappe.session.user != "Guest":
        try:
            from thinknxg_support.security import resolve_organization

            customer = resolve_organization(get_portal_user())
        except (PortalAccessError, frappe.PermissionError):
            pass
    return knowledge.record_feedback(name, vote, comment, customer=customer)


@frappe.whitelist(allow_guest=True, methods=["GET"])
def categories():
    _viewer()
    return knowledge.article_categories()
