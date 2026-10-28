"""One knowledge base for the portal, landing page and AI assistant: published Helpdesk articles (when
Helpdesk is installed) plus thinkDesk's own Support Knowledge Articles. Native ids start with "KB-"."""
from __future__ import annotations

import re

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


def _hd_rows(fields, extra=None, limit=1000):
    filters = {**helpdesk._published_filter(), **(extra or {})}
    return frappe.get_all("HD Article", filters=filters, fields=fields, order_by="title asc", limit=limit)


def _hd_category_labels() -> dict:
    if not frappe.db.exists("DocType", "HD Article Category"):
        return {}
    return {r.name: r.category_name or r.name for r in frappe.get_all(
        "HD Article Category", fields=["name", "category_name"], limit=1000)}


def sidebar(audience: str | None = None) -> list[dict]:
    """Categories in order, each with its article titles: the knowledge-base navigation."""
    if not available():
        raise IntegrationUnavailable("Knowledge base")
    groups, general = [], []
    if helpdesk.kb_available():
        has_cat = bool(capabilities_get().get("article_fields", {}).get("category"))
        rows = _hd_rows(["name", "title"] + (["category"] if has_cat else []))
        labels = _hd_category_labels()
        by_cat = {}
        for r in rows:
            (by_cat.setdefault(r.get("category"), []) if r.get("category") else general).append(
                {"name": r.name, "title": r.title})
        for cid, arts in sorted(by_cat.items(), key=lambda kv: (labels.get(kv[0]) or kv[0] or "").lower()):
            groups.append({"name": cid, "label": labels.get(cid) or cid, "articles": arts})
    if frappe.db.exists("DocType", ART):
        rows = frappe.get_all(ART, filters={"status": "Published", "audience": ["in", _aud(audience)]},
                              fields=["name", "title", "category"], order_by="sort_order asc, title asc", limit=2000)
        order = {r.name: i for i, r in enumerate(frappe.get_all(
            CAT, fields=["name"], order_by="sort_order asc, category_name asc", limit=1000))}
        by_cat = {}
        for r in rows:
            (by_cat.setdefault(r.category, []) if r.category else general).append({"name": r.name, "title": r.title})
        for cid in sorted(by_cat, key=lambda c: (order.get(c, 10_000), c.lower())):
            groups.append({"name": cid, "label": cid, "articles": by_cat[cid]})
    if general:
        groups.append({"name": "", "label": _("General"), "articles": general})
    return groups


def capabilities_get() -> dict:
    from thinknxg_support.integrations import capabilities

    return capabilities.get().get("helpdesk", {})


STOP = {"the", "and", "for", "with", "how", "what", "your", "from", "this", "that", "into", "when", "using"}


def related(name: str, audience: str | None = None, limit: int = 5) -> list[dict]:
    """Same category first, then articles whose titles share words with this one."""
    art = get_article(name, audience)  # also checks the viewer may read it
    limit = min(cint(limit) or 5, 10)
    out, seen = [], {name}
    for a in search_articles(None, art.get("category"), limit + 1, audience) if art.get("category") else []:
        if a["name"] not in seen:
            out.append({"name": a["name"], "title": a["title"], "category": a.get("category")})
            seen.add(a["name"])
    words = [w for w in re.findall(r"[\w']{4,}", (art.get("title") or "").lower()) if w not in STOP][:4]
    for w in words:
        if len(out) >= limit:
            break
        for a in search_articles(w, None, limit, audience):
            if a["name"] not in seen and len(out) < limit:
                out.append({"name": a["name"], "title": a["title"], "category": a.get("category")})
                seen.add(a["name"])
    return out[:limit]


def _visitor_key() -> str:
    import hashlib

    req = getattr(frappe.local, "request", None)
    ua = req.headers.get("User-Agent", "") if req is not None else ""
    raw = f"{getattr(frappe.local, 'request_ip', '') or ''}|{ua}|{frappe.local.site}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _who() -> dict:
    if frappe.session.user != "Guest":
        return {"user": frappe.session.user}
    return {"visitor": _visitor_key()}


def my_vote(name: str) -> str | None:
    if not frappe.db.exists("DocType", "Support Article Feedback"):
        return None
    return frappe.db.get_value("Support Article Feedback", {"article": name, **_who()}, "vote")


def record_feedback(name: str, vote: str, comment: str | None = None, customer: str | None = None) -> dict:
    if vote not in ("Helpful", "Not Helpful"):
        frappe.throw(_("Choose helpful or not helpful."))
    art = get_article(name)  # raises if this viewer cannot read it
    who = _who()
    from thinknxg_support.utils import clean_text

    comment = clean_text(comment, 1000) if comment else None
    existing = frappe.db.get_value("Support Article Feedback", {"article": name, **who}, ["name", "vote"], as_dict=True)
    if existing:
        values = {"vote": vote}
        if comment:
            values["comment"] = comment
        frappe.db.set_value("Support Article Feedback", existing.name, values)
    else:
        frappe.get_doc({"doctype": "Support Article Feedback", "article": name, "article_title": art.get("title"),
                        "article_doctype": ART if str(name).startswith("KB-") else "HD Article", "vote": vote,
                        "comment": comment, "customer": customer, **who}).insert(ignore_permissions=True)
    if str(name).startswith("KB-") and frappe.db.exists(ART, name):
        counts = dict(frappe.get_all("Support Article Feedback", filters={"article": name},
                                     fields=["vote", {"COUNT": "*", "as": "n"}], group_by="vote", as_list=True))
        frappe.db.set_value(ART, name, {"helpful_votes": cint(counts.get("Helpful")),
                                        "not_helpful_votes": cint(counts.get("Not Helpful"))}, update_modified=False)
    return {"vote": vote}


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
