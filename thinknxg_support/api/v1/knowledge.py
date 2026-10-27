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
    return knowledge.get_article(name)


@frappe.whitelist(allow_guest=True, methods=["GET"])
def categories():
    _viewer()
    return knowledge.article_categories()
