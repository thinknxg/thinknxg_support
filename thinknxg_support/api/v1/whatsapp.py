"""Meta WhatsApp Cloud API webhook: GET verification handshake, POST signed events."""
import json

import frappe
from werkzeug.wrappers import Response

from thinknxg_support.audit import log_event
from thinknxg_support.integrations import whatsapp


@frappe.whitelist(allow_guest=True, methods=["GET", "POST"])
def webhook(**kwargs):
    req = frappe.request
    if req.method == "GET":
        args = req.args
        if whatsapp.verify_subscription(args.get("hub.mode"), args.get("hub.verify_token")):
            return Response(args.get("hub.challenge") or "", status=200, mimetype="text/plain")
        return Response("forbidden", status=403, mimetype="text/plain")

    raw = req.get_data(cache=True)
    if not whatsapp.verify_signature(raw, req.headers.get("X-Hub-Signature-256")):
        log_event("Webhook", severity="Warning", details="whatsapp webhook signature rejected", user="Guest")
        return Response("invalid signature", status=403, mimetype="text/plain")
    if not frappe.db.get_single_value("Support Portal Settings", "enable_whatsapp"):
        return Response("disabled", status=200, mimetype="text/plain")  # 200 so Meta stops retrying
    try:
        payload = json.loads(raw or b"{}")
    except ValueError:
        return Response("bad request", status=400, mimetype="text/plain")
    try:
        whatsapp.handle_webhook(payload)
    except Exception:
        frappe.log_error(title="thinkNXG Support: WhatsApp webhook failed")
        return Response("error", status=500, mimetype="text/plain")  # Meta retries; processing is idempotent
    return Response("ok", status=200, mimetype="text/plain")
