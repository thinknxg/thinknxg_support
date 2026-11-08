"""Privacy requests: export or erase one person's personal data in support chats.

Erase anonymises instead of deleting the conversation, so counts and response times in reports stay right:
names, e-mail, phone and WhatsApp number, IP, sign-in tokens, message text, AI summaries and entities, feedback
comments, alert texts and attachments are removed; copies in Raven channels are deleted. ERPNext customers and
contacts and Helpdesk tickets are business records: they are listed for you to handle where they live, not changed.
The audit log records counts only, never the person's details.
"""
from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import now_datetime, strip_html

REQ = "Support Privacy Request"
CONV = "Support Conversation Link"
MSG = "Support Portal Message"
ERASED = "[erased]"


def digits(value: str | None) -> str:
    return "".join(ch for ch in (value or "") if ch.isdigit())[-15:]


def _contacts(email, phone) -> list[str]:
    names = set()
    if email:
        names |= set(frappe.get_all("Contact Email", filters={"email_id": email, "parenttype": "Contact"}, pluck="parent"))
    if phone and len(phone) >= 7:
        for row in frappe.get_all("Contact Phone", filters={"phone": ["like", f"%{phone[-9:]}"]}, fields=["parent", "phone"]):
            if digits(row.phone).endswith(phone[-9:]):
                names.add(row.parent)
    return list(names)


def matches(email=None, phone=None, customer=None) -> list[str]:
    found = set()
    if email:
        found |= set(frappe.get_all(CONV, filters={"guest_email": email}, pluck="name"))
        user = frappe.db.get_value("User", {"email": email}, "name")
        if user:
            found |= set(frappe.get_all(CONV, filters={"started_by": user}, pluck="name"))
    if phone and len(phone) >= 7:
        tail = phone[-9:]
        for field in ("guest_phone", "whatsapp_number"):
            for row in frappe.get_all(CONV, filters={field: ["like", f"%{tail}"]}, fields=["name", field]):
                if digits(row.get(field)).endswith(tail):
                    found.add(row.name)
    contacts = _contacts(email, phone)
    if contacts:
        found |= set(frappe.get_all(CONV, filters={"contact": ["in", contacts]}, pluck="name"))
    if customer:
        found |= set(frappe.get_all(CONV, filters={"customer": customer}, pluck="name"))
    return sorted(found)


def _files(msg_names):
    if not msg_names:
        return []
    return frappe.get_all("File", filters={"attached_to_doctype": MSG, "attached_to_name": ["in", msg_names]},
                          fields=["name", "file_name", "attached_to_name"])


def review(name: str) -> dict:
    req = frappe.get_doc(REQ, name)
    convs = matches(req.email, req.phone, req.customer)
    msgs = frappe.get_all(MSG, filters={"conversation": ["in", convs or [""]]}, pluck="name")
    linked = []
    for c in frappe.get_all(CONV, filters={"name": ["in", convs or [""]]}, fields=["helpdesk_ticket", "customer", "contact"]):
        if c.helpdesk_ticket:
            linked.append(f"HD Ticket {c.helpdesk_ticket}")
        if c.contact:
            linked.append(f"Contact {c.contact}")
        if c.customer:
            linked.append(f"Customer {c.customer}")
    for contact in _contacts(req.email, req.phone):
        linked.append(f"Contact {contact}")
    req.db_set({"conversations": len(convs), "messages": len(msgs), "files": len(_files(msgs)), "status": "Reviewed",
                "linked_records": "\n".join(sorted(set(linked)))[:2000] or None})
    return {"conversations": len(convs), "messages": len(msgs),
            "summary": _("{0} chats, {1} messages, {2} files.").format(len(convs), len(msgs), len(_files(msgs)))}


def run(name: str, confirm: str | None = None) -> dict:
    req = frappe.get_doc(REQ, name)
    if req.status == "Completed":
        frappe.throw(_("This request is already completed."))
    if req.status != "Reviewed":
        frappe.throw(_("Find the chats first, and check what was found."))
    if not req.identity_verified:
        frappe.throw(_("Confirm that you have verified the requester's identity."))
    if req.request_type == "Erase" and (confirm or "").strip() != "ERASE":
        frappe.throw(_("Type ERASE to confirm."))
    convs = matches(req.email, req.phone, req.customer)
    out = export(req, convs) if req.request_type == "Export" else erase(convs)
    req.db_set({"status": "Completed", "completed_on": now_datetime(), "completed_by": frappe.session.user,
                "conversations": out["conversations"], "messages": out["messages"], "files": out["files"],
                **({"export_file": out["file_url"]} if out.get("file_url") else {})})
    from thinknxg_support.audit import log_event

    log_event(f"Privacy {req.request_type}", severity="Warning" if req.request_type == "Erase" else "Info",
              reference_doctype=REQ, reference_name=req.name,
              details={k: out[k] for k in ("conversations", "messages", "files")}, commit=True)
    return out


def export(req, convs) -> dict:
    data = {"generated_on": str(now_datetime()), "request": req.name, "site": frappe.utils.get_url(), "conversations": []}
    total_msgs = total_files = 0
    for name in convs:
        c = frappe.get_doc(CONV, name)
        filters = {"conversation": name}
        if not req.include_internal_notes:
            filters["is_internal"] = 0
        msgs = frappe.get_all(MSG, filters=filters, fields=["name", "creation", "direction", "sender_name", "content",
                                                            "is_internal", "channel"], order_by="creation asc")
        files = {f.attached_to_name: f.file_name for f in _files([m.name for m in msgs])}
        fb = frappe.get_all("Support Chat Feedback", filters={"conversation": name},
                            fields=["rating", "resolved", "comment", "submitted_on"])
        data["conversations"].append({
            "id": c.name, "subject": c.subject, "channel": c.channel, "started": str(c.creation),
            "closed": str(c.closed_on) if c.closed_on else None, "name": c.guest_name, "email": c.guest_email,
            "phone": c.guest_phone or c.whatsapp_number, "rating": c.chat_rating,
            "messages": [{"at": str(m.creation), "from": "you" if m.direction == "Inbound" else (m.sender_name or "support"),
                          "text": strip_html(m.content or ""), "internal_note": bool(m.is_internal),
                          "attachment": files.get(m.name)} for m in msgs],
            "feedback": [{k: str(v) if v is not None else None for k, v in f.items()} for f in fb],
        })
        total_msgs += len(msgs)
        total_files += len(files)
    f = frappe.get_doc({"doctype": "File", "file_name": f"privacy-export-{req.name}.json", "is_private": 1,
                        "content": json.dumps(data, ensure_ascii=False, indent=2).encode(),
                        "attached_to_doctype": REQ, "attached_to_name": req.name})
    f.insert(ignore_permissions=True)
    return {"conversations": len(convs), "messages": total_msgs, "files": total_files, "file_url": f.file_url}


def erase(convs) -> dict:
    total_msgs = total_files = 0
    raven = frappe.db.exists("DocType", "Raven Message")
    for name in convs:
        msgs = frappe.get_all(MSG, filters={"conversation": name}, pluck="name")
        for f in _files(msgs):
            frappe.delete_doc("File", f.name, ignore_permissions=True, force=True)
            total_files += 1
        for m in msgs:
            frappe.db.set_value(MSG, m, {"content": f"<p>{ERASED}</p>", "attachment": None, "ai_entities": None,
                                         "ai_intent": None, "actions_json": None, "reactions_json": None},
                                update_modified=False)
        if msgs and frappe.db.exists("DocType", "Support Message Revision"):  # 1.14: earlier versions of messages
            frappe.db.delete("Support Message Revision", {"message": ["in", msgs]})
        frappe.db.set_value(MSG, {"conversation": name, "direction": "Inbound"}, "sender_name", _("Customer"),
                            update_modified=False)
        total_msgs += len(msgs)
        for mp in frappe.get_all("Support Message Mapping", filters={"conversation": name, "provider": "Raven"},
                                 pluck="external_message_id"):
            if raven and mp and frappe.db.exists("Raven Message", mp):
                frappe.delete_doc("Raven Message", mp, ignore_permissions=True, force=True)
        frappe.db.set_value(CONV, name, {
            "subject": _("Erased conversation"), "guest_name": _("Erased"), "guest_email": None, "guest_phone": None,
            "guest_ip": None, "guest_token_hash": None, "survey_token_hash": None, "whatsapp_number": None,
            "whatsapp_profile_name": None, "source_page": None, "summary": None, "intent": None,
            "closure_notes": None, "external_conversation_id": None, "last_message_reference": None,
        }, update_modified=False)
        for fb in frappe.get_all("Support Chat Feedback", filters={"conversation": name}, pluck="name"):
            frappe.db.set_value("Support Chat Feedback", fb, {"comment": None, "customer_name": None},
                                update_modified=False)
        frappe.db.set_value("Support Agent Alert", {"reference_doctype": CONV, "reference_name": name},
                            {"title": _("Erased conversation"), "body": None}, update_modified=False)
    frappe.db.commit()
    return {"conversations": len(convs), "messages": total_msgs, "files": total_files}
