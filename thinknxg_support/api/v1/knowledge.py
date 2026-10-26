from __future__ import annotations

import frappe

from thinknxg_support.integrations import helpdesk
from thinknxg_support.security import get_portal_user
from thinknxg_support.utils import require_module


@frappe.whitelist(methods=["GET"])
def search(q=None, category=None, limit=10):
    require_module("knowledge")
    get_portal_user()
    return helpdesk.search_articles(q, category, limit)


@frappe.whitelist(methods=["GET"])
def article(name):
    require_module("knowledge")
    get_portal_user()
    return helpdesk.get_article(name)


@frappe.whitelist(methods=["GET"])
def categories():
    require_module("knowledge")
    get_portal_user()
    return helpdesk.article_categories()
