"""Frappe Helpdesk adapter. Helpdesk stays the source of truth for tickets,
SLA, assignment and the knowledge base; this module only reads/writes through
documented document APIs and never exposes internal comments (HD Ticket Comment).
"""
from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, getdate, now_datetime, nowdate, strip_html

from thinknxg_support.integrations import IntegrationUnavailable, capabilities
from thinknxg_support.security import PortalAccessError, PortalUser, log_denied
from thinknxg_support.utils import _request_cache, clean_html, settings

TICKET = "HD Ticket"
DEFAULT_STATUS_CATEGORY = {
    "Open": "Open", "Replied": "Paused", "Paused": "Paused", "Resolved": "Resolved", "Closed": "Resolved",
}
TICKET_LIST_FIELDS = ["name", "subject", "status", "priority", "ticket_type", "agent_group", "opening_date",
                      "response_by", "resolution_by", "agreement_status", "modified", "raised_by", "customer"]


def available() -> bool:
    return bool(settings().enable_helpdesk) and bool(capabilities.get().get("helpdesk", {}).get("ok"))


def require():
    if not available():
        raise IntegrationUnavailable("Ticketing", _("Please contact us by email in the meantime."))


def _tf(field: str) -> bool:
    return capabilities.has_ticket_field(field)


def _existing(fields: list[str]) -> list[str]:
    return [f for f in fields if f == "name" or f == "modified" or _tf(f)]


# ------------------------------------------------------------------ mapping
def hd_customer_for(customer: str, create: bool = False) -> str | None:
    if not capabilities.get().get("helpdesk", {}).get("customer_doctype"):
        return None
    name = frappe.db.get_value("Customer", customer, "customer_name") or customer
    for candidate in (customer, name):
        if frappe.db.exists("HD Customer", candidate):
            return candidate
    if create and settings().auto_create_helpdesk_customer:
        doc = frappe.get_doc({"doctype": "HD Customer", "customer_name": name})
        doc.insert(ignore_permissions=True)
        return doc.name
    return None


def status_categories() -> dict:
    key = "thinknxg_support_status_cat"
    if key in _request_cache():
        return _request_cache()[key]
    mapping = dict(DEFAULT_STATUS_CATEGORY)
    if capabilities.get().get("helpdesk", {}).get("status_doctype"):
        meta = frappe.get_meta("HD Ticket Status")
        if meta.has_field("category"):
            for row in frappe.get_all("HD Ticket Status", fields=["name", "category"]):
                if row.category:
                    mapping[row.name] = row.category
    _request_cache()[key] = mapping
    return mapping


def category_of(status: str | None) -> str:
    return status_categories().get(status or "", "Open")


def _granted_hd_customers(pu: PortalUser) -> set:
    return {c for c in (hd_customer_for(x) for x in pu.customers) if c}


# ------------------------------------------------------------------ access
def assert_ticket_access(pu: PortalUser, ticket: str, customer: str) -> dict:
    """Return the ticket row if the user may see it, else raise (no existence leak)."""
    require()
    fields = _existing(["name", "raised_by", "customer", "contact", "subject", "status"])
    row = frappe.db.get_value(TICKET, ticket, fields, as_dict=True) if ticket else None
    if row and _ticket_visible(pu, row, customer):
        return row
    log_denied(pu, TICKET if row else None, ticket, "ticket access denied")
    raise PortalAccessError(_("Ticket not found."))


def _ticket_visible(pu: PortalUser, row, customer: str) -> bool:
    own = (row.get("raised_by") or "").strip().lower() == pu.email.lower() or (
        row.get("contact") and row.get("contact") in pu.contacts
    )
    hd_cust = hd_customer_for(customer)
    if own:
        # own tickets are visible unless they belong to an organisation the user is not granted
        return not row.get("customer") or row.get("customer") in _granted_hd_customers(pu)
    if hd_cust and row.get("customer") == hd_cust and pu.can("tickets.organization", customer):
        return True
    return False


# ------------------------------------------------------------------ reads
def list_tickets(pu: PortalUser, customer: str, scope: str = "own", status: str | None = None,
                 search: str | None = None, start: int = 0, page_length: int = 20) -> dict:
    require()
    hd_cust = hd_customer_for(customer)
    filters = {}
    or_filters = None
    if scope == "organization":
        if not pu.can("tickets.organization", customer):
            log_denied(pu, "Customer", customer, "org ticket list denied")
            raise PortalAccessError(_("You do not have organisation-wide ticket access."))
        if not hd_cust:
            return {"tickets": [], "total": 0}
        filters["customer"] = hd_cust
    else:
        or_filters = [[TICKET, "raised_by", "=", pu.email]]
        if pu.contacts and _tf("contact"):
            or_filters.append([TICKET, "contact", "in", pu.contacts])

    if status:
        wanted = [s for s, c in status_categories().items() if c == status] or [status]
        filters["status"] = ["in", wanted]
    if search:
        search = strip_html(search)[:100]
        if search.isdigit():
            filters["name"] = int(search)
        else:
            filters["subject"] = ["like", f"%{search}%"]

    fields = _existing(TICKET_LIST_FIELDS)
    start, page_length = cint(start), min(cint(page_length) or 20, 100)
    if scope == "organization":
        rows = frappe.get_all(TICKET, filters=filters, fields=fields, order_by="modified desc",
                              start=start, page_length=page_length)
        total = frappe.db.count(TICKET, filters=filters)
    else:
        # own tickets in the active organisation, plus own tickets with no organisation
        rows = frappe.get_all(TICKET, filters=filters, or_filters=or_filters, fields=fields,
                              order_by="modified desc", limit=500)
        if _tf("customer"):
            rows = [r for r in rows if not r.get("customer") or r.get("customer") == hd_cust]
        total = len(rows)
        rows = rows[start:start + page_length]
    return {"tickets": [_shape_ticket(r, pu) for r in rows], "total": total}


def _shape_ticket(r, pu: PortalUser) -> dict:
    cat = category_of(r.get("status"))
    overdue = bool(r.get("resolution_by") and cat != "Resolved" and r.get("resolution_by") < now_datetime())
    return {
        "name": r.get("name"),
        "subject": r.get("subject"),
        "status": r.get("status"),
        "status_category": cat,
        "priority": r.get("priority"),
        "ticket_type": r.get("ticket_type"),
        "team": r.get("agent_group"),
        "opened_on": r.get("opening_date"),
        "response_by": r.get("response_by"),
        "resolution_by": r.get("resolution_by"),
        "sla_status": r.get("agreement_status"),
        "overdue": overdue,
        "modified": r.get("modified"),
        "is_mine": (r.get("raised_by") or "").lower() == pu.email.lower(),
    }


def counts(pu: PortalUser, customer: str) -> dict:
    if not available():
        return {}
    scope = "organization" if pu.can("tickets.organization", customer) else "own"
    data = list_tickets(pu, customer, scope=scope, page_length=100)["tickets"]
    out = {"open": 0, "waiting": 0, "resolved": 0, "overdue": 0}
    for t in data:
        if t["status_category"] == "Open":
            out["open"] += 1
        elif t["status_category"] == "Paused":
            out["waiting"] += 1
        else:
            out["resolved"] += 1
        if t["overdue"]:
            out["overdue"] += 1
    out["recent"] = data[:5]
    out["scope"] = scope
    return out


def get_ticket(pu: PortalUser, ticket: str, customer: str) -> dict:
    assert_ticket_access(pu, ticket, customer)
    fields = _existing(TICKET_LIST_FIELDS + ["description", "feedback_rating", "feedback_text", "resolution_date"])
    row = frappe.db.get_value(TICKET, ticket, fields, as_dict=True)
    data = _shape_ticket(row, pu)
    data["description"] = clean_html(row.get("description") or "", max_len=200000)
    data["rating"] = round(flt(row.get("feedback_rating")) * 5) if row.get("feedback_rating") else None
    data["feedback_text"] = row.get("feedback_text")
    data["can_reopen"] = can_reopen(row)
    data["can_rate"] = data["status_category"] == "Resolved" and _tf("feedback_rating") and not data["rating"]
    data["timeline"] = _timeline(ticket, pu)
    data["attachments"] = _ticket_files(ticket)
    return data


def _timeline(ticket: str, pu: PortalUser) -> list[dict]:
    comms = frappe.get_all(
        "Communication",
        filters={"reference_doctype": TICKET, "reference_name": ticket, "communication_type": "Communication"},
        fields=["name", "content", "sender", "sender_full_name", "sent_or_received", "creation"],
        order_by="creation asc",
        limit=500,
    )
    files_by_comm = {}
    if comms:
        for f in frappe.get_all("File", filters={"attached_to_doctype": "Communication",
                                                 "attached_to_name": ["in", [c.name for c in comms]]},
                                fields=["name", "file_name", "attached_to_name", "file_size"]):
            files_by_comm.setdefault(f.attached_to_name, []).append(
                {"name": f.name, "file_name": f.file_name, "file_size": f.file_size})
    out = []
    for c in comms:
        from_customer = c.sent_or_received == "Received"
        out.append({
            "id": c.name,
            "from_customer": from_customer,
            # agent identity limited to first name; customers see their colleagues' names
            "author": (c.sender_full_name or c.sender or "") if from_customer
            else ((c.sender_full_name or "").split(" ")[0] or _("Support")),
            "is_me": from_customer and (c.sender or "").lower() == pu.email.lower(),
            "content": clean_html(c.content or "", max_len=500000),
            "created": c.creation,
            "attachments": files_by_comm.get(c.name, []),
        })
    return out


def _ticket_files(ticket: str) -> list[dict]:
    return frappe.get_all("File", filters={"attached_to_doctype": TICKET, "attached_to_name": ticket},
                          fields=["name", "file_name", "file_size", "creation"])


def file_belongs_to_ticket(file_name: str, ticket: str) -> bool:
    f = frappe.db.get_value("File", file_name, ["attached_to_doctype", "attached_to_name"], as_dict=True)
    if not f:
        return False
    if f.attached_to_doctype == TICKET and str(f.attached_to_name) == str(ticket):
        return True
    if f.attached_to_doctype == "Communication":
        c = frappe.db.get_value("Communication", f.attached_to_name,
                                ["reference_doctype", "reference_name", "communication_type"], as_dict=True)
        return bool(c and c.reference_doctype == TICKET and str(c.reference_name) == str(ticket)
                    and c.communication_type == "Communication")
    return False


def can_reopen(row) -> bool:
    if category_of(row.get("status")) != "Resolved":
        return False
    days = cint(settings().reopen_window_days)
    if not days:
        return False
    since = row.get("resolution_date") or row.get("modified")
    return bool(since and getdate(since) >= getdate(add_days(nowdate(), -days)))


# ------------------------------------------------------------------ writes
def create_ticket(subject: str, description: str, raised_by: str, customer: str | None = None,
                  ticket_type: str | None = None, priority: str | None = None, agent_group: str | None = None,
                  contact: str | None = None, via: str = "portal") -> str:
    require()
    s = settings()
    values = {
        "doctype": TICKET,
        "subject": frappe.utils.strip_html(subject)[:140],
        "description": clean_html(description),
        "raised_by": raised_by,
    }
    optional = {
        "customer": hd_customer_for(customer, create=True) if customer else None,
        "contact": contact,
        "ticket_type": ticket_type or s.default_ticket_type,
        "priority": priority or s.default_priority,
        "agent_group": agent_group,
        "via_customer_portal": 1,
    }
    for key, val in optional.items():
        if val and _tf(key):
            if key in ("ticket_type", "priority", "agent_group"):
                linked = {"ticket_type": "HD Ticket Type", "priority": "HD Ticket Priority", "agent_group": "HD Team"}[key]
                if frappe.db.exists("DocType", linked) and not frappe.db.exists(linked, val):
                    continue
            values[key] = val
    doc = frappe.get_doc(values)
    doc.flags.thinknxg_support_via = via
    doc.insert(ignore_permissions=True)
    return str(doc.name)


def add_reply(pu: PortalUser, ticket: str, customer: str, message: str, file_names: list[str] | None = None) -> str:
    assert_ticket_access(pu, ticket, customer)
    message = clean_html(message)
    if not strip_html(message).strip() and not file_names:
        frappe.throw(_("Please write a message."))
    doc = frappe.get_doc(TICKET, ticket)
    if capabilities.get()["helpdesk"].get("reply_via_contact"):
        try:
            doc.reply_via_contact(message=message, attachments=file_names or [])
            return "ok"
        except TypeError:
            pass  # signature changed: fall back to a plain Communication
    comm = frappe.get_doc({
        "doctype": "Communication",
        "communication_type": "Communication",
        "communication_medium": "Email",
        "sent_or_received": "Received",
        "subject": f"Re: {doc.subject}",
        "content": message,
        "sender": pu.email,
        "sender_full_name": pu.full_name,
        "reference_doctype": TICKET,
        "reference_name": ticket,
    })
    comm.insert(ignore_permissions=True)
    for fname in file_names or []:
        frappe.db.set_value("File", fname, {"attached_to_doctype": "Communication", "attached_to_name": comm.name})
    if category_of(doc.status) == "Paused":
        status_dt = capabilities.get()["helpdesk"].get("status_doctype")
        if not status_dt or frappe.db.exists(status_dt, "Open"):
            doc.db_set("status", "Open")
    return comm.name


def rate(pu: PortalUser, ticket: str, customer: str, stars: int, comment: str | None = None):
    row = assert_ticket_access(pu, ticket, customer)
    if category_of(row.status) != "Resolved":
        frappe.throw(_("You can rate a ticket once it is resolved."))
    if not _tf("feedback_rating"):
        raise IntegrationUnavailable("Ticket rating")
    stars = max(1, min(5, cint(stars)))
    doc = frappe.get_doc(TICKET, ticket)
    doc.feedback_rating = stars / 5.0
    if comment and _tf("feedback_text"):
        doc.feedback_text = frappe.utils.strip_html(comment)[:1000]
    doc.flags.ignore_permissions = True
    doc.save()


def reopen(pu: PortalUser, ticket: str, customer: str):
    assert_ticket_access(pu, ticket, customer)
    fields = _existing(["name", "status", "modified", "resolution_date"])
    row = frappe.db.get_value(TICKET, ticket, fields, as_dict=True)
    if not can_reopen(row):
        frappe.throw(_("This ticket can no longer be reopened. Please raise a new ticket."))
    doc = frappe.get_doc(TICKET, ticket)
    doc.status = "Open"
    doc.flags.ignore_permissions = True
    doc.save()


# ------------------------------------------------------------------ knowledge base
def _published_filter() -> dict:
    af = capabilities.get().get("helpdesk", {}).get("article_fields", {})
    if af.get("status"):
        return {"status": "Published"}
    if af.get("published"):
        return {"published": 1}
    return {}


def kb_available() -> bool:
    return bool(settings().enable_helpdesk and capabilities.get().get("helpdesk", {}).get("article_doctype"))


def search_articles(query: str | None, category: str | None = None, limit: int = 10) -> list[dict]:
    if not kb_available():
        raise IntegrationUnavailable("Knowledge base")
    af = capabilities.get()["helpdesk"].get("article_fields", {})
    filters = _published_filter()
    if category and af.get("category"):
        filters["category"] = category
    or_filters = None
    if query:
        q = f"%{strip_html(query)[:100]}%"
        or_filters = [["HD Article", "title", "like", q], ["HD Article", "content", "like", q]]
    fields = ["name", "title", "modified"] + (["category"] if af.get("category") else []) + ["content"]
    rows = frappe.get_all("HD Article", filters=filters, or_filters=or_filters, fields=fields,
                          order_by="modified desc", limit=min(cint(limit) or 10, 50))
    return [{
        "name": r.name, "title": r.title, "category": r.get("category"), "modified": r.modified,
        "excerpt": strip_html(r.content or "")[:220],
    } for r in rows]


def get_article(name: str) -> dict:
    if not kb_available():
        raise IntegrationUnavailable("Knowledge base")
    filters = {"name": name, **_published_filter()}
    af = capabilities.get()["helpdesk"].get("article_fields", {})
    fields = ["name", "title", "content", "modified"] + (["category"] if af.get("category") else [])
    rows = frappe.get_all("HD Article", filters=filters, fields=fields, limit=1)
    if not rows:
        raise frappe.DoesNotExistError(_("Article not found."))
    r = rows[0]
    return {"name": r.name, "title": r.title, "category": r.get("category"), "modified": r.modified,
            "content": clean_html(r.content or "", max_len=1000000)}


def article_categories() -> list[dict]:
    hd = capabilities.get().get("helpdesk", {})
    if not hd.get("article_category_doctype"):
        return []
    fields = ["name"] + (["category_name"] if hd.get("category_fields", {}).get("category_name") else [])
    return [{"name": r.name, "label": r.get("category_name") or r.name}
            for r in frappe.get_all("HD Article Category", fields=fields, order_by="name asc", limit=100)]


def ticket_types() -> list[str]:
    if not frappe.db.exists("DocType", "HD Ticket Type"):
        return []
    return frappe.get_all("HD Ticket Type", pluck="name", order_by="name asc", limit=100)


def priorities() -> list[str]:
    if not frappe.db.exists("DocType", "HD Ticket Priority"):
        return []
    return frappe.get_all("HD Ticket Priority", pluck="name", limit=20)
