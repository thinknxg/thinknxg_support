"""Staff ticket operations through the installed Frappe Helpdesk's own agent methods.

Detects what the installed version offers (HD Ticket Status, Comment vs HD Ticket Comment, reply_via_agent,
assign_agent, SLA fields) so one app works across Helpdesk versions. Helpdesk's permission hooks decide which tickets
an agent can list and open (team restrictions included): lists use frappe.get_list as the agent, lookups
doc.check_permission.
"""
from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import cint, strip_html

T = "HD Ticket"


def available() -> bool:
    return bool(frappe.db.exists("DocType", T))


def _meta():
    return frappe.get_meta(T)


def is_hd_agent(user: str | None = None) -> bool:
    user = user or frappe.session.user
    try:
        from helpdesk.utils import is_agent

        return bool(is_agent(user))
    except Exception:
        return bool(frappe.db.exists("HD Agent", {"user": user, "is_active": 1})) if frappe.db.exists("DocType", "HD Agent") \
            else user == "Administrator"


def statuses() -> list[dict]:
    if frappe.db.exists("DocType", "HD Ticket Status"):
        fields = ["name"] + [f for f in ("category", "label_agent", "color") if frappe.get_meta("HD Ticket Status").has_field(f)]
        rows = frappe.get_all("HD Ticket Status", fields=fields, order_by="creation asc")
        return [{"name": r.name, "label": r.get("label_agent") or r.name, "category": r.get("category"),
                 "color": r.get("color")} for r in rows]
    opts = (_meta().get_field("status").options or "").split("\n")
    cat = {"Open": "Open", "Replied": "Paused", "Paused": "Paused", "Resolved": "Resolved", "Closed": "Resolved"}
    return [{"name": o, "label": o, "category": cat.get(o, "Open"), "color": None} for o in opts if o]


def priorities() -> list[str]:
    if frappe.db.exists("DocType", "HD Ticket Priority"):
        return frappe.get_all("HD Ticket Priority", pluck="name", order_by="integer_value desc" if
                              frappe.get_meta("HD Ticket Priority").has_field("integer_value") else "name asc")
    return [o for o in (_meta().get_field("priority").options or "").split("\n") if o]


def _assignees(row) -> list[str]:
    try:
        return json.loads(row.get("_assign") or "[]")
    except ValueError:
        return []


LIST_FIELDS = ["name", "subject", "status", "priority", "raised_by", "customer", "contact", "agent_group", "_assign",
               "modified", "creation", "opening_date", "response_by", "resolution_by", "agreement_status",
               "first_responded_on", "status_category", "_seen"]


def _fields():
    m = _meta()
    return [f for f in LIST_FIELDS if f in ("name", "modified", "creation", "_assign", "_seen") or m.has_field(f)]


def ticket_summary(r) -> dict:
    users = _assignees(r)
    seen = []
    try:
        seen = json.loads(r.get("_seen") or "[]")
    except ValueError:
        pass
    return {"id": str(r.name), "subject": r.get("subject") or "", "status": r.get("status"),
            "status_category": r.get("status_category"), "priority": r.get("priority"), "raised_by": r.get("raised_by"),
            "customer": r.get("customer"), "contact": r.get("contact"), "team": r.get("agent_group"),
            "assignees": [{"user": u, "name": frappe.utils.get_fullname(u)} for u in users],
            "sla": {"response_by": _iso(r.get("response_by")), "resolution_by": _iso(r.get("resolution_by")),
                    "status": r.get("agreement_status"), "first_responded_on": _iso(r.get("first_responded_on"))},
            "created_at": _iso(r.get("opening_date") or r.get("creation")), "modified": _iso(r.get("modified")),
            "unread": frappe.session.user not in seen}


def _iso(v):
    if not v:
        return None
    return frappe.utils.get_datetime(v).isoformat() if not isinstance(v, str) or " " in v or "T" in v else v


def list_tickets(view: str = "mine", status: str | None = None, priority: str | None = None, q: str | None = None,
                 cursor: str | None = None, limit: int = 30) -> dict:
    from thinknxg_support.api.staff import cursors

    limit = max(1, min(cint(limit) or 30, 50))
    filters = []
    user = frappe.session.user
    if view == "mine":
        filters.append([T, "_assign", "like", f'%"{user}"%'])
    elif view == "unassigned":
        filters.append([T, "_assign", "not like", '%"%'])  # no user in the list (also matches empty / "[]")
    if status == "open":
        cats = [s["name"] for s in statuses() if s["category"] in ("Open", "Paused")] or ["Open", "Replied", "Paused"]
        filters.append([T, "status", "in", cats])
    elif status == "closed":
        cats = [s["name"] for s in statuses() if s["category"] == "Resolved"] or ["Resolved", "Closed"]
        filters.append([T, "status", "in", cats])
    elif status:
        filters.append([T, "status", "=", status])
    if priority:
        filters.append([T, "priority", "=", priority])
    or_filters = None
    if q:
        like = f"%{strip_html(q)[:80]}%"
        or_filters = [[T, "subject", "like", like], [T, "raised_by", "like", like], [T, "name", "like", like]]
    after = cursors.decode(cursor)
    if after:
        filters.append([T, "modified", "<=", after["t"]])
    rows = frappe.get_list(T, filters=filters, or_filters=or_filters, fields=_fields(),
                           order_by="modified desc, name desc", limit_page_length=limit + 25)
    if after:  # stable: skip rows at the same timestamp already returned
        rows = [r for r in rows if (str(r.modified), str(r.name)) < (after["t"], after["n"])]
    page = rows[:limit]
    nxt = cursors.encode(str(page[-1].modified), str(page[-1].name)) if len(rows) > limit and page else None
    return {"items": [ticket_summary(r) for r in page], "next_cursor": nxt}


def get_ticket(name: str):
    doc = frappe.get_doc(T, name)
    doc.check_permission("read")
    return doc


def ticket_detail(name: str) -> dict:
    doc = get_ticket(name)
    out = ticket_summary(doc.as_dict())
    out["description"] = doc.get("description") or ""
    conv = frappe.db.get_value("Support Conversation Link", {"helpdesk_ticket": doc.name}, "name")
    out["linked_conversation"] = conv
    out["can_write"] = bool(frappe.has_permission(T, "write", doc))
    out["statuses"] = statuses()
    out["priorities"] = priorities()
    return out


def timeline(name: str, cursor: str | None = None, limit: int = 30) -> dict:
    """Customer emails and replies (Communication) and agent-only notes (Comment / HD Ticket Comment), newest first."""
    from thinknxg_support.api.staff import cursors

    get_ticket(name)
    limit = max(1, min(cint(limit) or 30, 50))
    after = cursors.decode(cursor)
    cond = {"creation": ["<=", after["t"]]} if after else {}
    items = []
    for c in frappe.get_all("Communication", filters={"reference_doctype": T, "reference_name": name,
                                                      "communication_type": "Communication", **cond},
                            fields=["name", "creation", "sent_or_received", "sender", "sender_full_name", "content",
                                    "recipients", "cc", "delivery_status", "subject"],
                            order_by="creation desc, name desc", limit=limit + 10):
        items.append({"id": c.name, "kind": "email", "internal": False,
                      "direction": "inbound" if c.sent_or_received == "Received" else "outbound",
                      "author": c.sender_full_name or c.sender, "author_email": c.sender, "html": c.content or "",
                      "to": c.recipients, "cc": c.cc, "delivery": c.delivery_status, "created_at": _iso(c.creation),
                      "_t": str(c.creation)})
    for cm in frappe.get_all("Comment", filters={"reference_doctype": T, "reference_name": name,
                                                 "comment_type": "Comment", **cond},
                             fields=["name", "creation", "comment_email", "comment_by", "content"],
                             order_by="creation desc, name desc", limit=limit + 10):
        items.append({"id": cm.name, "kind": "note", "internal": True, "direction": "internal",
                      "author": cm.comment_by or cm.comment_email, "author_email": cm.comment_email,
                      "html": cm.content or "", "created_at": _iso(cm.creation), "_t": str(cm.creation)})
    if frappe.db.exists("DocType", "HD Ticket Comment") and frappe.get_meta("HD Ticket Comment").has_field("reference_ticket"):
        for cm in frappe.get_all("HD Ticket Comment", filters={"reference_ticket": name, **cond},
                                 fields=["name", "creation", "commented_by", "content"], order_by="creation desc", limit=limit + 10):
            items.append({"id": cm.name, "kind": "note", "internal": True, "direction": "internal",
                          "author": frappe.utils.get_fullname(cm.commented_by), "author_email": cm.commented_by,
                          "html": cm.content or "", "created_at": _iso(cm.creation), "_t": str(cm.creation)})
    items.sort(key=lambda x: (x["_t"], x["id"]), reverse=True)
    if after:
        items = [i for i in items if (i["_t"], i["id"]) < (after["t"], after["n"])]
    page = items[:limit]
    nxt = cursors.encode(page[-1]["_t"], page[-1]["id"]) if len(items) > limit and page else None
    for i in page:
        i.pop("_t", None)
    return {"items": list(reversed(page)), "next_cursor": nxt}  # oldest first within the page


def reply(name: str, html: str) -> dict:
    """Send the customer a reply through Helpdesk's agent workflow (email to the ticket's contact)."""
    doc = get_ticket(name)
    doc.check_permission("write")
    if hasattr(doc, "reply_via_agent"):
        doc.reply_via_agent(message=html)
    else:
        frappe.throw(_("This Helpdesk version has no agent reply method; reply from the Helpdesk app."))
    last = frappe.get_all("Communication", filters={"reference_doctype": T, "reference_name": name, "sent_or_received": "Sent"},
                          fields=["name", "creation"], order_by="creation desc", limit=1)
    return {"id": last[0].name if last else None, "kind": "email"}


def note(name: str, html: str) -> dict:
    doc = get_ticket(name)
    if hasattr(doc, "new_comment"):
        cid = doc.new_comment(content=html)
        return {"id": cid, "kind": "note"}
    if frappe.db.exists("DocType", "HD Ticket Comment"):
        c = frappe.get_doc({"doctype": "HD Ticket Comment", "reference_ticket": name, "content": html,
                            "commented_by": frappe.session.user}).insert()
        return {"id": c.name, "kind": "note"}
    c = doc.add_comment("Comment", html)
    return {"id": c.name, "kind": "note"}


def update(name: str, values: dict, expected_modified: str | None = None) -> dict:
    from thinknxg_support.api.staff.errors import Conflict

    doc = get_ticket(name)
    doc.check_permission("write")
    if expected_modified and str(doc.modified) != str(expected_modified) and \
            frappe.utils.get_datetime(doc.modified) > frappe.utils.get_datetime(expected_modified):
        raise Conflict(_("Someone else changed this ticket. Reload to see the latest."), current=ticket_summary(doc.as_dict()))
    allowed = {"status", "priority", "agent_group"}
    changed = {k: v for k, v in (values or {}).items() if k in allowed and v is not None and v != doc.get(k)}
    if "status" in changed and changed["status"] not in [s["name"] for s in statuses()]:
        frappe.throw(_("Unknown status."))
    if not changed:
        return ticket_summary(doc.as_dict())
    doc.update(changed)
    doc.save()  # as the agent: Helpdesk validation, SLA and permissions apply
    return ticket_summary(doc.as_dict())


def assign(name: str, agent: str, expected_assignees: list[str] | None = None) -> dict:
    from thinknxg_support.api.staff.errors import Conflict

    doc = get_ticket(name)
    doc.check_permission("write")
    current = _assignees(doc.as_dict())
    if expected_assignees is not None and sorted(current) != sorted(expected_assignees):
        raise Conflict(_("This ticket's owner changed. Reload to see the latest."), current=ticket_summary(doc.as_dict()))
    if not is_hd_agent(agent):
        frappe.throw(_("{0} is not a Helpdesk agent.").format(agent))
    if current and agent not in current:
        from frappe.desk.form.assign_to import remove

        for u in current:
            remove(T, name, u)
    if agent not in current:
        if hasattr(doc, "assign_agent"):
            doc.assign_agent(agent)
        else:
            from frappe.desk.form.assign_to import add

            add({"assign_to": [agent], "doctype": T, "name": name})
    return ticket_summary(frappe.get_doc(T, name).as_dict())
