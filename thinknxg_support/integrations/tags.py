"""Conversation tags, stored the Frappe way (_user_tags and Tag Link), so the desk list, the sidebar and reports
filter by them without anything new. Access is checked by the caller."""
from __future__ import annotations

import frappe
from frappe import _

CONV = "Support Conversation Link"
MAX_TAGS = 10


def clean(tag: str) -> str:
    tag = " ".join((tag or "").replace(",", " ").split())[:40]
    if not tag:
        frappe.throw(_("A tag cannot be empty."))
    return tag


def of(value: str | None) -> list[str]:
    return [t for t in (value or "").split(",") if t.strip()]


def get(name: str) -> list[str]:
    return of(frappe.db.get_value(CONV, name, "_user_tags"))


def update(name: str, add: list[str] | None = None, remove: list[str] | None = None) -> list[str]:
    from frappe.desk.doctype.tag.tag import DocTags

    dt = DocTags(CONV)
    current = get(name)
    for t in remove or []:
        t = clean(t)
        if t in current:
            dt.remove(name, t)
            current.remove(t)
    for t in add or []:
        t = clean(t)
        if t not in current:
            if len(current) >= MAX_TAGS:
                frappe.throw(_("A conversation can have up to {0} tags.").format(MAX_TAGS))
            dt.add(name, t)
            current.append(t)
    return get(name)


def suggestions(limit: int = 50) -> list[str]:
    """Tags already used on conversations, most used first."""
    rows = frappe.db.sql("select tag, count(*) n from `tabTag Link` where document_type=%s group by tag "
                         "order by n desc, tag asc limit %s", (CONV, int(limit)), as_dict=True)
    return [r.tag for r in rows]
