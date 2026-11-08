"""Leads from chats.

Target: Support Portal Settings > Leads > Create Leads In. "Automatic" uses thinkNXG CRM's CRM Lead when that app is
installed on the site, otherwise ERPNext Lead; "Off" switches lead features off. An existing lead with the same
e-mail or phone is linked instead of creating a duplicate. The chat is added to the lead's timeline (a comment with
the summary and a link), and its outcome when the chat ends.
"""
from __future__ import annotations

import re

import frappe
from frappe import _
from frappe.utils import cint, escape_html, get_url, strip_html

CONV = "Support Conversation Link"
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _s():
    from thinknxg_support.utils import settings

    return settings()


def target() -> str | None:
    choice = _s().get("lead_target") or "Automatic"
    crm = bool(frappe.db.exists("DocType", "CRM Lead"))
    erp = bool(frappe.db.exists("DocType", "Lead"))
    if choice == "Off":
        return None
    if choice.startswith("thinkNXG CRM"):
        return "CRM Lead" if crm else None
    if choice == "ERPNext Lead":
        return "Lead" if erp else None
    return "CRM Lead" if crm else ("Lead" if erp else None)


def digits(v) -> str:
    return "".join(ch for ch in str(v or "") if ch.isdigit() or ch == "+")[:20]


def details(conv) -> dict:
    """What the chat knows about the person."""
    from thinknxg_support.integrations import escalations

    d = escalations._conv_details(conv)
    name = conv.get("guest_name") or (frappe.utils.get_fullname(conv.started_by)
                                      if conv.get("started_by") and conv.started_by != "Guest" else "")
    company = None
    if conv.get("customer"):
        company = frappe.db.get_value("Customer", conv.customer, "customer_name")
    return {"name": (name or "").strip() or None, "email": d.get("contact_email"),
            "phone": ("+" + d["contact_phone"]) if d.get("contact_phone") and str(d["contact_phone"]).isdigit()
            else d.get("contact_phone"), "company": company}


def _split(name: str) -> tuple[str, str | None]:
    parts = (name or "").strip().split(" ", 1)
    return (parts[0] or _("Chat visitor"))[:140], (parts[1][:140] if len(parts) > 1 else None)


def _source(doctype: str, label: str) -> str | None:
    if not label or not frappe.db.exists("DocType", doctype):
        return None
    if not frappe.db.exists(doctype, label):
        frappe.get_doc({"doctype": doctype, "source_name": label}).insert(ignore_permissions=True)
    return label


def find_existing(doctype: str, email: str | None, phone: str | None) -> str | None:
    email_f, phone_f = ("email", "mobile_no") if doctype == "CRM Lead" else ("email_id", "mobile_no")
    if email:
        name = frappe.db.get_value(doctype, {email_f: email}, "name")
        if name:
            return name
    tail = digits(phone).lstrip("+")[-9:]
    if len(tail) >= 7:
        for row in frappe.get_all(doctype, filters={phone_f: ["like", f"%{tail}"]}, fields=["name", phone_f], limit=5):
            if digits(row.get(phone_f)).endswith(tail):
                return row.name
    return None


def clean(values: dict) -> dict:
    v = {k: (str(values.get(k) or "").strip() or None) for k in ("name", "email", "phone", "company")}
    if v["email"]:
        v["email"] = v["email"].lower()[:140]
        if not EMAIL.match(v["email"]):
            frappe.throw(_("That e-mail address does not look right."))
    if v["phone"] and len(digits(v["phone"]).lstrip("+")) < 6:
        frappe.throw(_("That phone number does not look right."))
    if v["name"]:
        v["name"] = strip_html(v["name"])[:140]
    if v["company"]:
        v["company"] = strip_html(v["company"])[:140]
    return v


def create_lead(conv, values: dict | None = None, actor: str | None = None) -> dict:
    """Create (or link) the lead for this chat. Returns {doctype, name, created}."""
    if conv.get("lead") and conv.get("lead_doctype") and frappe.db.exists(conv.lead_doctype, conv.lead):
        return {"doctype": conv.lead_doctype, "name": conv.lead, "created": False}
    dt = target()
    if not dt:
        frappe.throw(_("Leads are switched off, or neither thinkNXG CRM nor ERPNext is installed."))
    v = clean({**{k: x for k, x in details(conv).items() if x}, **{k: x for k, x in (values or {}).items() if x}})
    if not (v["email"] or v["phone"]):
        frappe.throw(_("A lead needs an e-mail address or a phone number."))
    existing = find_existing(dt, v["email"], v["phone"])
    created = not existing
    if existing:
        name = existing
    else:
        first, last = _split(v["name"] or v["email"] or "")
        src = (_s().get("lead_source") or "Live Chat").strip()
        if dt == "CRM Lead":
            doc = {"doctype": dt, "first_name": first, "last_name": last, "email": v["email"], "mobile_no": v["phone"],
                   "organization": v["company"], "source": _source("CRM Lead Source", src)}
        else:
            doc = {"doctype": dt, "first_name": first, "last_name": last, "email_id": v["email"], "mobile_no": v["phone"],
                   "company_name": v["company"], "source": _source("Lead Source", src)}
        lead = frappe.get_doc({k: x for k, x in doc.items() if x is not None})
        lead.flags.ignore_permissions = True  # the chat's access was checked; support staff create leads from chats
        lead.flags.ignore_mandatory = False
        lead.insert()
        name = lead.name
    frappe.db.set_value(CONV, conv.name, {"lead_doctype": dt, "lead": name}, update_modified=False)
    conv.lead_doctype, conv.lead = dt, name
    timeline(conv, _("Lead {0} from this chat.").format(_("created") if created else _("linked")), summary=True)
    from thinknxg_support.audit import log_event

    log_event("Administrative Change", reference_doctype=CONV, reference_name=conv.name,
              details={"lead": f"{dt} {name}", "created": created}, user=actor)
    from thinknxg_support.integrations import lead_score

    lead_score.queue(conv.name)
    from thinknxg_support.integrations import analytics

    analytics.refresh()
    return {"doctype": dt, "name": name, "created": created}


def _conv_link(conv) -> str:
    return f"{get_url()}/app/support-chat?conversation={conv.name}"


def timeline(conv, headline: str, summary: bool = False, extra: list[str] | None = None):
    """A comment on the lead's timeline (works for ERPNext Lead and CRM Lead)."""
    if not (conv.get("lead") and conv.get("lead_doctype") and frappe.db.exists(conv.lead_doctype, conv.lead)):
        return
    parts = [f"<p><b>{escape_html(headline)}</b> <a href=\"{_conv_link(conv)}\">{escape_html(conv.name)}</a> · "
             f"{escape_html(conv.get('channel') or '')} · {escape_html(conv.subject or '')}</p>"]
    s = frappe.db.get_value(CONV, conv.name, "summary") if summary else None
    if s:
        parts.append(f"<p>{escape_html(strip_html(s))[:1200]}</p>")
    for line in extra or []:
        parts.append(f"<p>{escape_html(line)}</p>")
    frappe.get_doc({"doctype": "Comment", "comment_type": "Comment", "reference_doctype": conv.lead_doctype,
                    "reference_name": conv.lead, "content": "".join(parts),
                    "comment_email": "Administrator"}).insert(ignore_permissions=True)


def on_closed(conv):
    conv = frappe.get_doc(CONV, conv.name) if isinstance(conv, str) else conv
    if not conv.get("lead"):
        return
    row = frappe.db.get_value(CONV, conv.name, ["closure_reason", "issue_resolved", "needs_follow_up", "lead_score"],
                              as_dict=True) or {}
    extra = [x for x in (
        _("Reason: {0}").format(row.closure_reason) if row.get("closure_reason") else None,
        _("Issue resolved: {0}").format(row.issue_resolved) if row.get("issue_resolved") else None,
        _("Follow-up needed: {0}").format(row.needs_follow_up) if row.get("needs_follow_up") else None,
    ) if x]
    timeline(conv, _("Chat ended."), extra=extra)
    from thinknxg_support.integrations import lead_score

    lead_score.queue(conv.name)


def lead_view(conv) -> dict | None:
    if not conv.get("lead") or not conv.get("lead_doctype"):
        return None
    title_f = "lead_name"
    title = frappe.db.get_value(conv.lead_doctype, conv.lead, title_f) if frappe.db.exists(conv.lead_doctype, conv.lead) else None
    route = "crm/leads/" + conv.lead if conv.lead_doctype == "CRM Lead" else f"app/lead/{conv.lead}"
    return {"doctype": conv.lead_doctype, "name": conv.lead, "title": title or conv.lead, "url": f"{get_url()}/{route}",
            "score": cint(conv.get("lead_score")) if conv.get("lead_score") is not None else None,
            "reasons": conv.get("lead_score_reasons")}


def converted(doctype: str, names: list[str]) -> int:
    """How many of these leads became customers or deals."""
    if not names:
        return 0
    if doctype == "CRM Lead":
        field = "converted" if frappe.get_meta(doctype).has_field("converted") else None
        return frappe.db.count(doctype, {"name": ["in", names], field: 1}) if field else 0
    return frappe.db.count(doctype, {"name": ["in", names], "status": ["in", ["Converted", "Opportunity", "Quotation"]]})
