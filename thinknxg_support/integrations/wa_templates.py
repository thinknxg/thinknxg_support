"""1.17: WhatsApp message templates.

Templates are written and approved in WhatsApp Manager. This module reads them (sync), keeps where each {{variable}}
gets its value, builds the Cloud API components, and sends a template into a chat: from an agent, or from an
automation rule. Marketing templates go only to numbers that opted in. Nothing here creates a template in Meta.
"""
from __future__ import annotations

import json
import re

import frappe
from frappe import _
from frappe.utils import cint, now_datetime, strip_html

from thinknxg_support.utils import settings

TPL = "Support WhatsApp Template"
CONSENT = "Support WhatsApp Consent"
CONV = "Support Conversation Link"
MSG = "Support Portal Message"
VAR = re.compile(r"\{\{\s*([A-Za-z0-9_]+)\s*\}\}")
FIELDS = "name,language,status,category,components,parameter_format,quality_score,rejected_reason,id"
STATUS = {"APPROVED": "Approved", "PENDING": "Pending", "REJECTED": "Rejected", "PAUSED": "Paused",
          "DISABLED": "Disabled", "IN_APPEAL": "In Appeal", "PENDING_DELETION": "Disabled", "DELETED": "Deleted",
          "REINSTATED": "Approved", "FLAGGED": None}
CATEGORY = {"MARKETING": "Marketing", "UTILITY": "Utility", "AUTHENTICATION": "Authentication"}
QUALITY = {"GREEN": "High", "YELLOW": "Medium", "RED": "Low", "UNKNOWN": ""}
TEMPLATE_EVENTS = ("message_template_status_update", "message_template_quality_update", "template_category_update")
STOP_WORDS = {"stop", "stop all", "unsubscribe", "optout", "opt out", "إيقاف", "ايقاف", "توقف", "إلغاء الاشتراك",
              "الغاء الاشتراك"}
DEFAULT_STOP = "You will no longer receive marketing messages from us. Send START to receive them again."
DEFAULT_START = "Thank you, you will receive our updates again. Send STOP at any time to unsubscribe."
START_WORDS = {"start", "subscribe", "unstop", "opt in", "optin", "اشتراك", "ابدأ", "ابدا"}

# What Meta's error codes mean for the person looking at a failed message.
ERRORS = {
    131047: "The 24-hour reply window had closed: only an approved template can be sent now.",
    131026: "The number cannot receive WhatsApp messages (not on WhatsApp, or it has not accepted the latest terms).",
    131049: "Meta chose not to deliver this marketing message to protect the customer's experience (frequency limit). "
            "Try again later or use a utility template if the message is a service update.",
    131048: "Meta limited sending because too many recipients reported or blocked these messages.",
    131056: "Too many messages to this number in a short time. Wait before sending again.",
    131030: "The number is not on the list of allowed test recipients for this WhatsApp account.",
    131031: "The WhatsApp Business Account is locked. Check WhatsApp Manager.",
    132000: "The number of variables does not match the template.",
    132001: "This template does not exist in this language. Sync templates and check the name and language.",
    132005: "The translated text is too long for the template.",
    132007: "A character format in the message breaks WhatsApp's policy.",
    132012: "A variable has the wrong format for the template (for example a newline or a long text).",
    132015: "The template is paused by Meta (low quality). Edit it in WhatsApp Manager.",
    132016: "The template is disabled by Meta.",
    130472: "The customer's number is part of a Meta experiment and cannot receive marketing messages now.",
}


class TemplateError(frappe.ValidationError):
    pass


class OptInRequired(TemplateError):
    pass


def explain(code, fallback: str | None = None) -> str | None:
    return ERRORS.get(cint(code)) or fallback


# ------------------------------------------------------------------ sync
def _vars(text: str | None) -> list[str]:
    seen = []
    for m in VAR.finditer(text or ""):
        if m.group(1) not in seen:
            seen.append(m.group(1))
    return seen


def _example(component: dict, kind: str, name: str, index: int) -> str:
    ex = component.get("example") or {}
    if kind == "header":
        vals = ex.get("header_text") or []
        return str(vals[index]) if index < len(vals) else ""
    named = ex.get(f"{kind}_text_named_params") or ex.get("header_text_named_params") or []
    for n in named:
        if n.get("param_name") == name:
            return str(n.get("example") or "")
    rows = (ex.get("body_text") or [[]])[0] if kind == "body" else []
    return str(rows[index]) if index < len(rows) else ""


def parse(components: list[dict], named: bool) -> dict:
    """What the template shows and which variables it has. Pure: no database."""
    out = {"header_format": "", "header_text": "", "body_text": "", "footer_text": "", "buttons": [], "variables": []}
    for c in components or []:
        t = (c.get("type") or "").upper()
        if t == "HEADER":
            fmt = (c.get("format") or "TEXT").title()
            out["header_format"] = fmt
            if fmt == "Text":
                out["header_text"] = c.get("text") or ""
                for i, name in enumerate(_vars(out["header_text"])):
                    out["variables"].append({"key": f"header.{name}", "component": "Header", "position": name,
                                             "example": _example(c, "header", name, i), "button_index": 0})
        elif t == "BODY":
            out["body_text"] = c.get("text") or ""
            for i, name in enumerate(_vars(out["body_text"])):
                out["variables"].append({"key": f"body.{name}", "component": "Body", "position": name,
                                         "example": _example(c, "body", name, i), "button_index": 0})
            if c.get("add_security_recommendation") and not out["body_text"]:
                out["body_text"] = _("{{1}} is your verification code.")
                out["variables"].append({"key": "body.1", "component": "Body", "position": "1", "example": "123456",
                                         "button_index": 0})
        elif t == "FOOTER":
            out["footer_text"] = c.get("text") or (
                _("This code expires in {0} minutes.").format(c["code_expiration_minutes"])
                if c.get("code_expiration_minutes") else "")
        elif t == "BUTTONS":
            for idx, b in enumerate(c.get("buttons") or []):
                bt = (b.get("type") or "").upper()
                out["buttons"].append({"type": bt, "text": b.get("text") or "", "url": b.get("url") or "",
                                       "phone": b.get("phone_number") or "", "index": idx})
                if bt == "URL" and VAR.search(b.get("url") or ""):
                    ex = (b.get("example") or [""])[0]
                    out["variables"].append({"key": f"button{idx}.1", "component": "Button", "position": "1",
                                             "example": str(ex).rsplit("/", 1)[-1], "button_index": idx})
                elif bt == "COPY_CODE":
                    out["variables"].append({"key": f"button{idx}.code", "component": "Button", "position": "code",
                                             "example": str((b.get("example") or [""])[0]), "button_index": idx})
    return out


def _status_of(raw: str | None) -> str:
    return STATUS.get((raw or "").upper()) or "Unknown"


def upsert(t: dict) -> str:
    """Create or update the template record for one entry of Meta's list. Keeps the variable map the admin set."""
    named = (t.get("parameter_format") or "").upper() == "NAMED"
    p = parse(t.get("components") or [], named)
    key = f"{t['name']}-{t['language']}"
    doc = frappe.get_doc(TPL, key) if frappe.db.exists(TPL, key) else frappe.new_doc(TPL)
    doc.update({
        "template_name": t["name"], "language": t["language"], "category": CATEGORY.get((t.get("category") or "").upper()),
        "status": _status_of(t.get("status")), "parameter_format": "Named" if named else "Positional",
        "quality": QUALITY.get(((t.get("quality_score") or {}).get("score") or "").upper(), ""),
        "rejected_reason": None if (t.get("rejected_reason") or "NONE") == "NONE" else t.get("rejected_reason"),
        "meta_id": str(t.get("id") or ""), "header_format": p["header_format"], "header_text": p["header_text"],
        "body_text": p["body_text"], "footer_text": p["footer_text"], "buttons_json": json.dumps(p["buttons"]),
        "components_json": json.dumps(t.get("components") or []), "last_synced_on": now_datetime(),
    })
    auth = doc.category == "Authentication"
    old = {v.key: v for v in doc.get("variables") or []}
    doc.set("variables", [])
    for v in p["variables"]:
        prev = old.get(v["key"])
        doc.append("variables", {**v, "source": "Entered by Agent" if auth else (prev.source if prev else "Entered by Agent"),
                                 "fixed_text": prev.fixed_text if prev else None})
    doc.flags.ignore_permissions = True
    doc.save()
    return doc.name


def sync() -> str:
    from thinknxg_support.integrations import whatsapp

    s = settings()
    waba = (s.whatsapp_business_account_id or "").strip()
    if not whatsapp.available():
        frappe.throw(_("Fill in and save the WhatsApp settings first."))
    if not waba:
        frappe.throw(_("Enter the WhatsApp Business Account ID in Support Portal Settings to read your templates."))
    seen, path = set(), f"{waba}/message_templates?fields={FIELDS}&limit=100"
    try:
        while path:
            data = whatsapp._api(path, method="GET", absolute=path.startswith("http"))
            for t in data.get("data") or []:
                if t.get("name") and t.get("language"):
                    seen.add(upsert(t))
            path = (data.get("paging") or {}).get("next")
    except whatsapp.WhatsAppError as e:
        msg = _("WhatsApp did not return the templates: {0}").format(e)
        frappe.db.set_single_value("Support Portal Settings", "whatsapp_template_sync", msg[:500])
        frappe.throw(msg)
    gone = 0
    for name in frappe.get_all(TPL, filters={"status": ["!=", "Deleted"]}, pluck="name"):
        if name not in seen:
            frappe.db.set_value(TPL, name, "status", "Deleted", update_modified=False)
            gone += 1
    result = _("{0} templates read from WhatsApp, {1} no longer exist there.").format(len(seen), gone)
    frappe.db.set_single_value("Support Portal Settings", {"whatsapp_template_sync": result,
                                                           "whatsapp_templates_synced_on": now_datetime()})
    frappe.clear_document_cache("Support Portal Settings", "Support Portal Settings")
    return result


def sync_daily():
    """Scheduler: keep statuses fresh even when the status webhook is not subscribed."""
    from thinknxg_support.integrations import whatsapp

    s = settings()
    if whatsapp.available() and (s.whatsapp_business_account_id or "").strip() and frappe.db.count(TPL):
        try:
            sync()
        except Exception:
            frappe.log_error(title="thinkNXG Support: WhatsApp template sync failed")


# ------------------------------------------------------------------ variables
def _first(name: str | None) -> str:
    return (name or "").strip().split(" ")[0] if name else ""


def customer_name(conv) -> str:
    name = conv.get("whatsapp_profile_name") or conv.get("guest_name")
    if not name and conv.get("customer"):
        name = frappe.db.get_value("Customer", conv.customer, "customer_name")
    if not name and conv.get("started_by"):
        name = frappe.db.get_value("User", conv.started_by, "full_name")
    return (name or "").strip()


def source_value(source: str, fixed: str | None, conv, user: str | None) -> str:
    from thinknxg_support.constants import PORTAL_ROUTE

    if source == "Fixed Text":
        return fixed or ""
    if source == "Customer Name":
        return customer_name(conv)
    if source == "Customer First Name":
        return _first(customer_name(conv))
    if source == "Phone Number":
        return f"+{conv.whatsapp_number}" if conv.get("whatsapp_number") else (conv.get("guest_phone") or "")
    if source == "Chat Reference":
        return conv.name
    if source == "Ticket Reference":
        return conv.get("helpdesk_ticket") or ""
    if source in ("Agent Name", "Agent First Name"):
        who = user or conv.get("assigned_agent")
        full = (frappe.db.get_value("User", who, "full_name") if who and who not in ("Guest", "Administrator") else "") \
            or (settings().portal_title or "")
        return _first(full) if source == "Agent First Name" else full
    if source == "Company":
        return settings().portal_title or "thinkNXG Support"
    if source == "Portal Link":
        return frappe.utils.get_url(PORTAL_ROUTE)
    return fixed or ""  # Entered by Agent: the starting text


def _clean(v) -> str:
    """Meta rejects newlines, tabs and runs of 4+ spaces inside a variable (error 132018)."""
    v = re.sub(r"[\r\n\t]+", " ", str(v or ""))
    return re.sub(r" {4,}", "   ", v).strip()[:1000]


def prepare(tpl, conv, user: str | None = None, overrides: dict | None = None) -> dict:
    """The variables with their values (the agent's edits win) and the message as the customer will read it."""
    overrides = overrides or {}
    rows, values = [], {}
    for v in tpl.get("variables") or []:
        raw = overrides.get(v.key) or source_value(v.source, v.fixed_text, conv, user)
        value = _clean(raw)
        values[v.key] = value
        rows.append({"key": v.key, "component": v.component, "position": v.position, "example": v.example or "",
                     "source": v.source, "value": value, "button_index": v.button_index or 0})
    return {"variables": rows, "values": values, "text": render(tpl, values)}


def _fill(text: str, comp: str, values: dict) -> str:
    return VAR.sub(lambda m: values.get(f"{comp}.{m.group(1)}", "") or m.group(0), text or "")


def render(tpl, values: dict) -> dict:
    buttons = json.loads(tpl.buttons_json or "[]")
    return {"header": _fill(tpl.header_text, "header", values) if tpl.header_format == "Text" else "",
            "body": _fill(tpl.body_text, "body", values), "footer": tpl.footer_text or "",
            "buttons": [{"type": b["type"], "text": b["text"]} for b in buttons]}


def message_html(r: dict) -> str:
    esc = frappe.utils.escape_html
    parts = []
    if r["header"]:
        parts.append(f"<p><b>{esc(r['header'])}</b></p>")
    parts.append("".join(f"<p>{esc(p).replace(chr(10), '<br>')}</p>" for p in r["body"].split("\n\n") if p.strip()))
    if r["footer"]:
        parts.append(f"<p><small>{esc(r['footer'])}</small></p>")
    labels = [b["text"] for b in r["buttons"] if b["text"]]
    if labels:
        parts.append(f"<p><small>[{' · '.join(esc(x) for x in labels)}]</small></p>")
    return "".join(parts)


def components(tpl, values: dict) -> list[dict]:
    """The `components` of the Cloud API template message."""
    named = tpl.parameter_format == "Named"
    out = []

    def param(comp, name, position):
        p = {"type": "text", "text": _clean(values.get(f"{comp}.{position}"))}
        if named:
            p["parameter_name"] = name
        return p

    head = [v for v in tpl.variables if v.component == "Header"]
    if tpl.header_format == "Text" and head:
        out.append({"type": "header", "parameters": [param("header", v.position, v.position) for v in head]})
    elif tpl.header_format in ("Image", "Video", "Document"):
        if not tpl.header_media_url:
            raise TemplateError(_("This template has a {0} header: set the Header Media Link on the template first.")
                                .format(_(tpl.header_format)))
        kind = tpl.header_format.lower()
        out.append({"type": "header", "parameters": [{"type": kind, kind: {"link": tpl.header_media_url}}]})
    body = [v for v in tpl.variables if v.component == "Body"]
    if body:
        out.append({"type": "body", "parameters": [param("body", v.position, v.position) for v in body]})
    for b in json.loads(tpl.buttons_json or "[]"):
        idx = str(b["index"])
        if tpl.category == "Authentication" and b["type"] == "OTP":
            code = _clean(values.get("body.1"))
            out.append({"type": "button", "sub_type": "url", "index": idx, "parameters": [{"type": "text", "text": code}]})
        elif b["type"] == "URL" and f"button{idx}.1" in values:
            out.append({"type": "button", "sub_type": "url", "index": idx,
                        "parameters": [{"type": "text", "text": _clean(values[f"button{idx}.1"])}]})
        elif b["type"] == "COPY_CODE" and f"button{idx}.code" in values:
            out.append({"type": "button", "sub_type": "copy_code", "index": idx,
                        "parameters": [{"type": "coupon_code", "coupon_code": _clean(values[f"button{idx}.code"])}]})
    return out


def check_complete(tpl, values: dict):
    missing = [v.key for v in tpl.variables if not (values.get(v.key) or "").strip()]
    if missing:
        raise TemplateError(_("Fill in every variable of the template ({0}).").format(", ".join(missing)))


# ------------------------------------------------------------------ opt-in and opt-out
def status_of(number: str | None) -> str | None:
    from thinknxg_support.integrations import whatsapp

    n = whatsapp.normalize(number)
    return frappe.db.get_value(CONSENT, n, "status") if n and frappe.db.exists(CONSENT, n) else None


def require_optin() -> bool:
    v = settings().get("whatsapp_require_optin")
    return True if v is None else bool(cint(v))


def record(number: str, status: str, source: str, note: str | None = None, conv=None, user: str | None = None) -> str:
    """Opted In / Opted Out for a number. A customer who opted out can only be opted in again by a manager (or by
    the customer, with START)."""
    from thinknxg_support.integrations import whatsapp

    n = whatsapp.normalize(number)
    if len(n) < 8:
        raise TemplateError(_("Enter the number with its country code."))
    current = status_of(n)
    if status == "Opted In" and current == "Opted Out" and source == "Agent" \
            and "Support Manager" not in frappe.get_roles(user or frappe.session.user) \
            and "System Manager" not in frappe.get_roles(user or frappe.session.user):
        raise TemplateError(_("This customer asked to stop marketing messages. Only a Support Manager can record a new "
                              "opt-in, or the customer can send START."))
    if current == status and not note:
        return n
    doc = frappe.get_doc(CONSENT, n) if current else frappe.new_doc(CONSENT)
    doc.update({"number": n, "status": status, "source": source, "note": (note or doc.note or "")[:500] or
                (_("Customer sent a message") if source == "Customer Message" else None)})
    if conv is not None:
        doc.contact = doc.contact or conv.get("contact")
        doc.customer = doc.customer or conv.get("customer")
    doc.flags.ignore_permissions = True
    doc.save()
    return n


def check_marketing(number: str | None):
    if not require_optin():
        return
    st = status_of(number)
    if st == "Opted In":
        return
    if st == "Opted Out":
        raise OptInRequired(_("This customer opted out of marketing messages."))
    raise OptInRequired(_("This customer has not agreed to receive marketing messages. Record how they agreed first."))


def keyword(text: str | None) -> str | None:
    t = re.sub(r"[\s.!؟?،,]+$", "", strip_html(text or "").strip().casefold())
    return "stop" if t in STOP_WORDS else "start" if t in START_WORDS else None


def on_inbound(conv, number: str, text: str | None) -> str | None:
    """STOP / START from the customer. Returns the keyword so the caller keeps the assistant from answering it."""
    kind = keyword(text)
    if not kind:
        return None
    record(number, "Opted Out" if kind == "stop" else "Opted In", "Customer Message",
           note=_("Customer wrote {0}").format((text or "").strip()[:20]), conv=conv)
    s = settings()
    reply = s.get("whatsapp_optout_reply" if kind == "stop" else "whatsapp_optin_reply")
    if reply is None:  # never set on this site: the defaults
        reply = DEFAULT_STOP if kind == "stop" else DEFAULT_START
    return kind if not reply.strip() else kind + "\n" + reply.strip()


# ------------------------------------------------------------------ what agents and rules can use
def usable(tpl) -> str | None:
    """None when the template can be sent, otherwise why not."""
    if not cint(tpl.enabled):
        return _("This template is switched off.")
    if tpl.status != "Approved":
        return _("This template is {0} in WhatsApp, so it cannot be sent.").format(_(tpl.status or "Unknown"))
    return None


def options(conv, user: str | None = None) -> list[dict]:
    """The templates an agent can choose for this chat, with the variables filled in as far as we know them."""
    out = []
    st = status_of(conv.get("whatsapp_number"))
    for name in frappe.get_all(TPL, filters={"enabled": 1, "status": "Approved"}, order_by="template_name asc, language asc",
                               pluck="name"):
        tpl = frappe.get_cached_doc(TPL, name)
        prep = prepare(tpl, conv, user)
        blocked = None
        if tpl.category == "Marketing" and require_optin() and st != "Opted In":
            blocked = "opted_out" if st == "Opted Out" else "no_optin"
        out.append({"name": tpl.name, "template_name": tpl.template_name, "language": tpl.language,
                    "category": tpl.category, "text": prep["text"], "variables": prep["variables"],
                    "raw": {"header": tpl.header_text if tpl.header_format == "Text" else "", "body": tpl.body_text,
                            "footer": tpl.footer_text or "", "buttons": json.loads(tpl.buttons_json or "[]")},
                    "needs_media": tpl.header_format in ("Image", "Video", "Document") and not tpl.header_media_url,
                    "blocked": blocked})
    return out


def consent_view(number: str | None) -> dict:
    from thinknxg_support.integrations import whatsapp

    num = whatsapp.normalize(number)
    row = frappe.db.get_value(CONSENT, num, ["status", "source", "note", "changed_on"], as_dict=True) if num else None
    return {"required": require_optin(), "status": row.status if row else None, "source": row.source if row else None,
            "note": row.note if row else None, "changed_on": str(row.changed_on) if row and row.changed_on else None}


def send(conv, template: str, overrides: dict | None = None, *, user: str | None = None, source: str = "desk",
         client_message_id: str | None = None, automatic: str | None = None, keep_status: bool = False) -> dict:
    """Send an approved template into a WhatsApp chat. `user` is the agent; automation passes `automatic` (the rule)."""
    from thinknxg_support.integrations import conversations

    if client_message_id:
        dup = frappe.db.get_value(MSG, {"conversation": conv.name, "client_message_id": client_message_id}, "name")
        if dup:
            return {"name": dup, "duplicate": True}
    if not frappe.db.exists(TPL, template):
        raise TemplateError(_("Unknown template. Sync templates from Meta first."))
    tpl = frappe.get_cached_doc(TPL, template)
    if conv.get("channel") != "WhatsApp" or not conv.get("whatsapp_number"):
        raise TemplateError(_("Templates are sent to WhatsApp chats only."))
    why = usable(tpl)
    if why:
        raise TemplateError(why)
    if tpl.category == "Marketing":
        check_marketing(conv.whatsapp_number)
    prep = prepare(tpl, conv, user, overrides)
    check_complete(tpl, prep["values"])
    comps = components(tpl, prep["values"])
    payload = {"name": tpl.template_name, "language": tpl.language, "components": comps, "doc": tpl.name}
    was_closed = conv.get("status") == "Closed"
    out = conversations.post_agent_message(
        conv, message_html(prep["text"]), source=source, client_message_id=client_message_id, template=payload,
        sender=user or "Administrator", sender_type="Agent" if user else "Bot",
        response_source=("Automation: " + automatic) if automatic else None)
    if was_closed and keep_status:
        frappe.db.set_value(CONV, conv.name, "status", "Closed", update_modified=False)
    return out


def start_chat(number: str, template: str, overrides: dict | None, user: str, customer: str | None = None,
               client_message_id: str | None = None) -> dict:
    """An agent starts the conversation: the first message must be a template (the customer has not written)."""
    from thinknxg_support import ratelimit
    from thinknxg_support.integrations import whatsapp

    ratelimit.check("wa_template_start", 60, 3600)
    n = whatsapp.normalize(number)
    if len(n) < 8:
        raise TemplateError(_("Enter the number with its country code."))
    name = frappe.db.get_value(CONV, {"channel": "WhatsApp", "whatsapp_number": n, "status": ["!=", "Closed"]}, "name",
                               order_by="creation desc")
    if name:
        conv = frappe.get_doc(CONV, name)
    else:
        contact = cust = u = None
        if cint(settings().whatsapp_link_contacts):
            contact, cust, u = whatsapp.match_contact(n)
        cust = customer or cust
        conv = frappe.get_doc({
            "doctype": CONV, "subject": _("WhatsApp: +{0}").format(n), "channel": "WhatsApp",
            "conversation_type": "Customer Chat", "status": "Open", "external_provider": "Portal Native",
            "whatsapp_number": n, "customer": cust, "contact": contact, "started_by": u, "handling": "Agent",
            "assigned_agent": user, "last_activity_at": now_datetime()})
        conv.insert(ignore_permissions=True)
    send(conv, template, overrides, user=user, source="app", client_message_id=client_message_id)
    return {"conversation": conv.name}


# ------------------------------------------------------------------ shared by the web console and the agent apps
def _values(values) -> dict:
    values = frappe.parse_json(values) if isinstance(values, str) and values else values
    return {str(k): ("" if v is None else str(v)) for k, v in (values or {}).items()}


def api_options(conv, user: str) -> dict:
    if conv.get("channel") != "WhatsApp":
        raise TemplateError(_("Templates are sent to WhatsApp chats only."))
    return {"templates": options(conv, user), "consent": consent_view(conv.whatsapp_number),
            "window_open": bool(conv.get("whatsapp_window_expires")
                                and frappe.utils.get_datetime(conv.whatsapp_window_expires) > now_datetime())}


def api_send(conv, template: str, values, cid: str | None, user: str, source: str) -> dict:
    return send(conv, template, _values(values), user=user, source=source, client_message_id=cid)


def api_consent(conv, status: str, note: str | None, user: str) -> dict:
    if status not in ("Opted In", "Opted Out"):
        raise TemplateError(_("Choose Opted In or Opted Out."))
    record(conv.whatsapp_number, status, "Agent", note=note, conv=conv, user=user)
    return consent_view(conv.whatsapp_number)


def api_start(number: str, template: str, values, cid: str | None, user: str, customer: str | None = None) -> dict:
    return start_chat(number, template, _values(values), user, customer, cid)


# ------------------------------------------------------------------ Meta's template events
def _find(value: dict) -> str | None:
    if value.get("message_template_id"):
        name = frappe.db.get_value(TPL, {"meta_id": str(value["message_template_id"])}, "name")
        if name:
            return name
    key = f"{value.get('message_template_name')}-{value.get('message_template_language')}"
    return key if frappe.db.exists(TPL, key) else None


def on_webhook(field: str, value: dict):
    """Status, quality and category changes of a template, pushed by Meta."""
    name = _find(value or {})
    if not name:
        return  # a template we have not synced yet: the next sync picks it up
    doc = frappe.get_doc(TPL, name)
    before = (doc.status, doc.quality, doc.category)
    if field == "message_template_status_update":
        event = (value.get("event") or "").upper()
        if STATUS.get(event):
            doc.status = STATUS[event]
        if event == "FLAGGED":
            doc.quality = "Low"
        doc.rejected_reason = None if (value.get("reason") or "NONE") == "NONE" else value.get("reason")
    elif field == "message_template_quality_update":
        doc.quality = QUALITY.get((value.get("new_quality_score") or "").upper(), doc.quality)
    elif field == "template_category_update":
        doc.category = CATEGORY.get((value.get("new_category") or "").upper(), doc.category)
    if (doc.status, doc.quality, doc.category) == before:
        return
    doc.flags.ignore_permissions = True
    doc.save()
    if doc.status in ("Paused", "Disabled", "Rejected") or doc.quality == "Low" or doc.category != before[2]:
        notify_managers(doc, before)


def notify_managers(doc, before):
    users = frappe.get_all("Has Role", filters={"role": "Support Manager", "parenttype": "User"}, pluck="parent")
    users = [u for u in dict.fromkeys(users) if frappe.db.get_value("User", u, "enabled") and u not in ("Administrator", "Guest")]
    what = []
    if doc.status != before[0]:
        what.append(_("status {0}").format(_(doc.status)))
    if doc.quality != before[1] and doc.quality:
        what.append(_("quality {0}").format(_(doc.quality)))
    if doc.category != before[2]:
        what.append(_("category {0}").format(_(doc.category or "")))
    subject = _("WhatsApp template {0} ({1}): {2}").format(doc.template_name, doc.language, ", ".join(what))
    for u in users:
        try:
            frappe.get_doc({"doctype": "Notification Log", "for_user": u, "type": "Alert", "subject": subject[:140],
                            "email_content": frappe.utils.escape_html(doc.rejected_reason or ""), "document_type": TPL,
                            "document_name": doc.name, "from_user": "Administrator"}).insert(ignore_permissions=True)
        except Exception:
            frappe.log_error(title="thinkNXG Support: template notification failed")


def on_send_error(template_doc: str | None, code):
    """A send failed because of the template itself: stop offering it until Meta's status says otherwise."""
    if not template_doc or not frappe.db.exists(TPL, template_doc):
        return
    new = {132015: "Paused", 132016: "Disabled", 132001: "Deleted"}.get(cint(code))
    if new and frappe.db.get_value(TPL, template_doc, "status") != new:
        doc = frappe.get_doc(TPL, template_doc)
        before = (doc.status, doc.quality, doc.category)
        frappe.db.set_value(TPL, template_doc, "status", new, update_modified=False)
        doc.status = new
        notify_managers(doc, before)


# ------------------------------------------------------------------ report
def report(start=None, end=None) -> list[dict]:
    """Per template: sent, delivered, read, failed between two dates (default: the last 30 days), with the most
    common failure reasons."""
    from frappe.utils import add_days, nowdate

    end = end or nowdate()
    start = start or add_days(end, -29)
    rows = frappe.get_all(MSG, filters={"wa_template": ["is", "set"], "direction": "Outbound",
                                        "creation": ["between", [f"{start} 00:00:00", f"{end} 23:59:59.999999"]]},
                          fields=["wa_template", "delivery_status", "delivery_code"], limit=50000)
    by = {}
    for r in rows:
        d = by.setdefault(r.wa_template, {"template": r.wa_template, "sent": 0, "delivered": 0, "read": 0, "failed": 0,
                                         "errors": {}})
        st = r.delivery_status or "Pending"
        if st == "Failed":
            d["failed"] += 1
            if r.delivery_code:
                d["errors"][int(r.delivery_code)] = d["errors"].get(int(r.delivery_code), 0) + 1
        elif st in ("Sent", "Delivered", "Read"):
            d["sent"] += 1
            d["delivered"] += st in ("Delivered", "Read")
            d["read"] += st == "Read"
    out = []
    for d in by.values():
        attempted = d["sent"] + d["failed"]
        meta = frappe.db.get_value(TPL, d["template"], ["template_name", "language", "category", "status", "quality"],
                                   as_dict=True) or {}
        d.update({"template_name": meta.get("template_name") or d["template"], "language": meta.get("language"),
                  "category": meta.get("category"), "status": meta.get("status"), "quality": meta.get("quality"),
                  "delivery_rate": round(100 * d["delivered"] / attempted) if attempted else 0,
                  "read_rate": round(100 * d["read"] / d["delivered"]) if d["delivered"] else 0,
                  "errors": [{"code": c, "count": n, "meaning": explain(c) or ""}
                             for c, n in sorted(d["errors"].items(), key=lambda x: -x[1])[:3]]})
        out.append(d)
    return sorted(out, key=lambda x: -(x["sent"] + x["failed"]))
