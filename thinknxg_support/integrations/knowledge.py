"""One knowledge base for the portal, landing page and AI assistant: published Helpdesk articles (when
Helpdesk is installed) plus thinkDesk's own Support Knowledge Articles. Native ids start with "KB-"."""
from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, strip_html

from thinknxg_support.integrations import IntegrationUnavailable, helpdesk
from thinknxg_support.utils import clean_html

ART = "Support Knowledge Article"
CAT = "Support Knowledge Category"


def native_available() -> bool:
    return bool(frappe.db.exists("DocType", ART) and frappe.db.exists(ART, {"status": "Published"}))


def available() -> bool:
    return helpdesk.kb_available() or native_available()


def viewer_audience() -> str:
    if frappe.session.user == "Guest":
        return "Everyone"
    from thinknxg_support.security import PortalAccessError, get_portal_user

    try:
        get_portal_user()
        return "Customers"
    except (PortalAccessError, frappe.AuthenticationError):
        return "Everyone"


def _aud(audience):
    return ["Everyone", "Customers"] if (audience or viewer_audience()) == "Customers" else ["Everyone"]


def search_articles(query: str | None = None, category: str | None = None, limit: int = 10,
                    audience: str | None = None) -> list[dict]:
    if not available():
        raise IntegrationUnavailable("Knowledge base")
    limit = min(cint(limit) or 10, 50)
    out = []
    if helpdesk.kb_available() and not (category and frappe.db.exists(CAT, category)):
        try:
            out.extend(helpdesk.search_articles(query, category, limit))
        except Exception:
            frappe.log_error(title="thinkNXG Support: Helpdesk article search failed")
    if frappe.db.exists("DocType", ART):
        filters = {"status": "Published", "audience": ["in", _aud(audience)]}
        if category:
            filters["category"] = category
        or_filters = None
        if query:
            q = f"%{strip_html(query)[:100]}%"
            or_filters = [[ART, "title", "like", q], [ART, "content", "like", q]]
        for r in frappe.get_all(ART, filters=filters, or_filters=or_filters, order_by="published_on desc",
                                fields=["name", "title", "category", "modified", "content"], limit=limit):
            out.append({"name": r.name, "title": r.title, "category": r.category, "modified": r.modified,
                        "excerpt": strip_html(r.content or "")[:220]})
    out.sort(key=lambda a: str(a.get("modified") or ""), reverse=True)
    return out[:limit]


def get_article(name: str, audience: str | None = None) -> dict:
    if name and str(name).startswith("KB-") and frappe.db.exists(ART, name):
        r = frappe.db.get_value(ART, name, ["name", "title", "content", "category", "modified", "status", "audience",
                                            "source_url", "licence"], as_dict=True)
        if r.status != "Published" or r.audience not in _aud(audience):
            raise frappe.DoesNotExistError(_("Article not found."))
        return {"name": r.name, "title": r.title, "category": r.category, "modified": r.modified,
                "content": clean_html(r.content or "", max_len=1000000)}
    return helpdesk.get_article(name)


def article_categories(audience: str | None = None) -> list[dict]:
    out = []
    if helpdesk.kb_available():
        out.extend(helpdesk.article_categories())
    if frappe.db.exists("DocType", CAT):
        used = set(frappe.get_all(ART, filters={"status": "Published", "audience": ["in", _aud(audience)]},
                                  pluck="category", distinct=True))
        for r in frappe.get_all(CAT, fields=["name", "category_name"], order_by="sort_order asc, category_name asc"):
            if r.name in used:
                out.append({"name": r.name, "label": r.category_name})
    return out
