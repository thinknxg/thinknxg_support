"""WhatsApp adapter: signatures, de-duplication, window handling and receipts (Graph API mocked)."""
import hashlib
import hmac
import json
from unittest.mock import patch

import frappe
from frappe.utils import add_to_date, now_datetime

from thinknxg_support.integrations import whatsapp
from thinknxg_support.tests.utils import BaseTestCase, as_user
from thinknxg_support.utils import clear_request_cache

SECRET = "app-secret-for-tests"


class TestWhatsApp(BaseTestCase):
    def setUp(self):
        as_user("Administrator")
        s = frappe.get_single("Support Portal Settings")
        s.update({"enable_whatsapp": 1, "whatsapp_phone_number_id": "1234567890", "whatsapp_access_token": "tok",
                  "whatsapp_app_secret": SECRET, "whatsapp_verify_token": "verify-me", "enable_raven": 0,
                  "whatsapp_template_name": "", "whatsapp_auto_reply": "", "whatsapp_link_contacts": 1})
        s.flags.ignore_permissions = True
        s.save()
        clear_request_cache()

    def test_signature(self):
        body = b'{"entry": []}'
        good = "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
        self.assertTrue(whatsapp.verify_signature(body, good))
        self.assertFalse(whatsapp.verify_signature(body, "sha256=" + "0" * 64))
        self.assertFalse(whatsapp.verify_signature(body + b" ", good))
        self.assertFalse(whatsapp.verify_signature(body, None))

    def test_subscription_handshake(self):
        self.assertTrue(whatsapp.verify_subscription("subscribe", "verify-me"))
        self.assertFalse(whatsapp.verify_subscription("subscribe", "wrong"))

    def test_normalize(self):
        self.assertEqual(whatsapp.normalize("+968 9123-4567"), "96891234567")

    def _inbound(self, msg_id, text="Hello", wa="96890000001"):
        with patch.object(whatsapp, "_send", return_value="wamid.read"):
            whatsapp.process_inbound({"id": msg_id, "from": wa, "type": "text", "text": {"body": text}}, "Salim")

    def test_inbound_creates_conversation_once(self):
        self._inbound("wamid.A1")
        self._inbound("wamid.A1")  # Meta retry
        self._inbound("wamid.A2", "Second")
        conv = frappe.get_all("Support Conversation Link", filters={"whatsapp_number": "96890000001", "status": ["!=", "Closed"]},
                              fields=["name", "whatsapp_window_expires", "channel"])
        self.assertEqual(len(conv), 1)
        self.assertEqual(conv[0].channel, "WhatsApp")
        self.assertEqual(frappe.db.count("Support Portal Message", {"conversation": conv[0].name}), 2)
        self.assertGreater(conv[0].whatsapp_window_expires, now_datetime())

    def test_contact_match_requires_single_owner(self):
        for name in ("_WA One", "_WA Two"):
            if not frappe.db.exists("Contact", {"first_name": name}):
                frappe.get_doc({"doctype": "Contact", "first_name": name,
                                "phone_nos": [{"phone": "+968 9555 1212", "is_primary_mobile_no": 1}]}).insert(ignore_permissions=True)
        self.assertEqual(whatsapp.match_contact("96895551212"), (None, None, None))

    def test_reply_inside_window_sends_text(self):
        self._inbound("wamid.B1", wa="96890000002")
        conv = frappe.get_doc("Support Conversation Link", {"whatsapp_number": "96890000002"})
        from thinknxg_support.integrations.conversations import post_agent_message

        with patch.object(whatsapp, "_send", return_value="wamid.out1") as send, \
                patch.object(frappe, "enqueue", lambda fn, **kw: fn(**{k: v for k, v in kw.items() if k == "message"})):
            post_agent_message(conv, "<p>Hi <b>Salim</b></p>")
        payload = send.call_args[0][0]
        self.assertEqual(payload["type"], "text")
        self.assertIn("*Salim*", payload["text"]["body"])
        msg = frappe.get_all("Support Portal Message", filters={"external_message_id": "wamid.out1"}, fields=["delivery_status"])
        self.assertEqual(msg[0].delivery_status, "Sent")

        whatsapp.update_status({"id": "wamid.out1", "status": "read"})
        whatsapp.update_status({"id": "wamid.out1", "status": "delivered"})  # out of order: must not regress
        self.assertEqual(frappe.db.get_value("Support Portal Message", {"external_message_id": "wamid.out1"},
                                             "delivery_status"), "Read")

    def test_reply_after_window_without_template_fails_clearly(self):
        self._inbound("wamid.C1", wa="96890000003")
        conv = frappe.get_doc("Support Conversation Link", {"whatsapp_number": "96890000003"})
        conv.db_set("whatsapp_window_expires", add_to_date(now_datetime(), hours=-1))
        from thinknxg_support.integrations.conversations import post_agent_message

        with patch.object(whatsapp, "_send") as send, \
                patch.object(frappe, "enqueue", lambda fn, **kw: fn(**{k: v for k, v in kw.items() if k == "message"})):
            r = post_agent_message(conv, "late reply")
        send.assert_not_called()
        row = frappe.db.get_value("Support Portal Message", r["name"], ["delivery_status", "delivery_error"], as_dict=True)
        self.assertEqual(row.delivery_status, "Failed")
        self.assertIn("24-hour", row.delivery_error)

    def test_webhook_ignores_other_numbers(self):
        payload = {"entry": [{"changes": [{"field": "messages", "value": {
            "metadata": {"phone_number_id": "999"}, "messages": [{"id": "wamid.X", "from": "1", "type": "text",
                                                                  "text": {"body": "x"}}]}}]}]}
        with patch.object(frappe, "enqueue") as enq:
            whatsapp.handle_webhook(json.loads(json.dumps(payload)))
        enq.assert_not_called()
