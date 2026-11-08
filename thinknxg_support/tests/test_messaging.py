"""1.14 increment 1: reply-to, edit with history, remove, reactions, visitor files and voice notes, WhatsApp."""
import json
from unittest.mock import patch

import frappe
from frappe.utils import add_to_date, now_datetime

from thinknxg_support.api.staff import v1
from thinknxg_support.integrations import conversations, live_chat, messaging, whatsapp
from thinknxg_support.tests.utils import BaseTestCase, as_user

CONV = "Support Conversation Link"
MSG = "Support Portal Message"
WEBM = b"\x1a\x45\xdf\xa3" + b"\x00" * 200
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100


def make_user(email, roles):
    if not frappe.db.exists("User", email):
        frappe.get_doc({"doctype": "User", "email": email, "first_name": email.split("@")[0], "send_welcome_email": 0,
                        "roles": [{"role": r} for r in roles]}).insert(ignore_permissions=True)
    return email


class FakeRequest:
    def __init__(self, files):
        self.files = FakeFiles(files)


class FakeFiles:
    def __init__(self, files):
        self._files = files

    def getlist(self, key):
        return [FakeStorage(n, c) for n, c in self._files]

    def __bool__(self):
        return bool(self._files)


class FakeStorage:
    def __init__(self, name, content):
        import io

        self.filename, self.stream = name, io.BytesIO(content)


class Base(BaseTestCase):
    def setUp(self):
        as_user("Administrator")
        frappe.db.set_single_value("Support Portal Settings", {
            "enable_live_chat": 1, "allow_guest_chat": 1, "guest_chat_rate_limit": 1000, "allow_customer_edits": 1,
            "customer_edit_minutes": 5, "allow_reactions": 1, "allow_guest_uploads": 1, "allow_voice_notes": 1,
            "max_voice_seconds": 120, "allowed_attachment_extensions": "pdf,png,jpg,txt", "max_attachment_mb": 5})
        frappe.db.set_single_value("Support AI Settings", {"enable_ai": 0, "analyze_messages": 0})
        frappe.clear_document_cache("Support Portal Settings", "Support Portal Settings")
        frappe.clear_document_cache("Support AI Settings", "Support AI Settings")
        frappe.cache.delete_keys("thinknxg_support:rl:")
        from thinknxg_support.utils import clear_request_cache

        clear_request_cache()
        self.agent = make_user("msg-agent@example.com", ["Support Agent"])
        self.other = make_user("msg-agent2@example.com", ["Support Agent"])
        self.manager = make_user("msg-manager@example.com", ["Support Manager", "Support Agent"])

    def tearDown(self):
        as_user("Administrator")

    def chat(self, text="Hello, my order is late"):
        as_user("Guest")
        with patch("thinknxg_support.integrations.ai.engine.respond"):
            r = live_chat.start_guest(text, name="Huda", email="huda@example.com")
        as_user("Administrator")
        frappe.db.set_value(CONV, r["conversation"], {"handling": "Agent", "assigned_agent": self.agent},
                            update_modified=False)
        return r["conversation"], r["token"], frappe.get_all(MSG, filters={"conversation": r["conversation"]}, pluck="name")[0]

    def agent_says(self, conv, text="We are checking", internal=0, **kw):
        as_user(self.agent)
        out = conversations.post_agent_message(frappe.get_doc(CONV, conv), f"<p>{text}</p>", internal=internal, **kw)
        return out["name"]

    def guest_view(self, conv, token):
        as_user("Guest")
        try:
            return {m["id"]: m for m in live_chat.guest_messages(conv, token)["messages"]}
        finally:
            as_user("Administrator")


class TestEditRemove(Base):
    def test_guest_edits_own_message_within_the_window_and_staff_see_history(self):
        conv, token, first = self.chat()
        as_user("Guest")
        live_chat.guest_edit(conv, token, first, "Hello, my order SO-9 is late")
        as_user("Administrator")
        view = self.guest_view(conv, token)[first]
        self.assertIn("SO-9", view["content"])
        self.assertTrue(view["edited"])
        self.assertTrue(view["can_edit"])
        as_user(self.agent)
        self.assertEqual([h["text"] for h in v1.message_history(conv, first)], ["Hello, my order is late"])
        frappe.db.set_value(MSG, first, "creation", add_to_date(now_datetime(), minutes=-6), update_modified=False)
        as_user("Guest")
        self.assertRaises(frappe.PermissionError, live_chat.guest_edit, conv, token, first, "too late")

    def test_nobody_changes_someone_elses_message(self):
        conv, token, first = self.chat()
        reply = self.agent_says(conv)
        as_user("Guest")
        self.assertRaises(frappe.PermissionError, live_chat.guest_edit, conv, token, reply, "hacked")
        self.assertRaises(frappe.PermissionError, live_chat.guest_remove, conv, token, reply)
        as_user(self.other)
        self.assertRaises(frappe.PermissionError, v1.edit_message, conv, reply, "not mine")
        as_user(self.agent)
        self.assertRaises(frappe.PermissionError, v1.edit_message, conv, first, "the customer's words")
        other_conv, other_token, _m = self.chat("Another visitor")
        as_user("Guest")
        self.assertRaises(Exception, live_chat.guest_edit, other_conv, other_token, first, "cross-chat")

    def test_removed_messages_are_hidden_from_customers_but_kept_for_staff(self):
        conv, token, first = self.chat()
        reply = self.agent_says(conv, "Your address is 12 Palm St")
        as_user(self.agent)
        v1.remove_message(conv, reply)
        view = self.guest_view(conv, token)[reply]
        self.assertTrue(view["removed"])
        self.assertNotIn("Palm", view["content"])
        as_user(self.agent)
        item = next(m for m in v1.messages(conv)["items"] if m["id"] == reply)
        self.assertTrue(item["removed"])
        self.assertIn("Palm", item["html"])  # staff and audit keep the original
        self.assertRaises(frappe.PermissionError, v1.edit_message, conv, reply, "again")

    def test_managers_may_remove_any_visible_message(self):
        conv, token, first = self.chat("abusive words")
        as_user(self.agent)
        self.assertRaises(frappe.PermissionError, v1.remove_message, conv, first)
        as_user(self.manager)
        v1.remove_message(conv, first)
        self.assertTrue(frappe.db.get_value(MSG, first, "hidden"))

    def test_whatsapp_messages_cannot_be_changed_once_sent(self):
        conv, token, first = self.chat()
        reply = self.agent_says(conv)
        frappe.db.set_value(MSG, reply, "channel", "WhatsApp", update_modified=False)
        as_user(self.agent)
        self.assertRaises(frappe.PermissionError, v1.edit_message, conv, reply, "changed")

    def test_changes_reach_polling_apps(self):
        conv, token, first = self.chat()
        reply = self.agent_says(conv)
        as_user(self.agent)
        page = v1.messages(conv)
        since = page["server_time"]
        frappe.db.set_value(MSG, reply, "modified", add_to_date(now_datetime(), seconds=-30), update_modified=False)
        v1.edit_message(conv, reply, "We have found it")
        later = v1.messages(conv, after=page["latest_cursor"], changed_since=since)
        self.assertEqual(later["items"], [])
        self.assertEqual([m["id"] for m in later["updated"]], [reply])
        self.assertTrue(later["updated"][0]["edited"])
        self.assertNotIn("updated", v1.messages(conv, after=page["latest_cursor"]))  # old apps: unchanged response


class TestReactionsAndReplies(Base):
    def test_reactions_toggle_and_show_whose(self):
        conv, token, first = self.chat()
        reply = self.agent_says(conv)
        as_user("Guest")
        live_chat.guest_react(conv, token, reply, "👍")
        as_user(self.agent)
        v1.react(conv, reply, "👍")
        item = next(m for m in v1.messages(conv)["items"] if m["id"] == reply)
        self.assertEqual(item["reactions"], [{"emoji": "👍", "count": 2, "mine": True}])
        v1.react(conv, reply, "👍")
        self.assertEqual(self.guest_view(conv, token)[reply]["reactions"], [{"emoji": "👍", "count": 1, "mine": True}])
        as_user("Guest")
        self.assertRaises(frappe.ValidationError, live_chat.guest_react, conv, token, reply, "💣")
        note = self.agent_says(conv, "staff only", internal=1)
        as_user("Guest")
        self.assertRaises(Exception, live_chat.guest_react, conv, token, note, "👍")

    def test_replies_quote_the_earlier_message(self):
        conv, token, first = self.chat()
        as_user(self.agent)
        out = v1.reply(conv, "Which order number?", "req-reply-1", reply_to=first)
        self.assertEqual(out["message"]["reply_to"]["id"], first)
        view = self.guest_view(conv, token)[out["message"]["id"]]
        self.assertEqual(view["reply_to"]["excerpt"], "Hello, my order is late")
        note = self.agent_says(conv, "VIP", internal=1)
        as_user(self.agent)
        self.assertRaises(frappe.ValidationError, v1.reply, conv, "quoting a note", "req-reply-2", reply_to=note)
        other, _t, other_first = self.chat("someone else")
        as_user(self.agent)
        self.assertRaises(frappe.ValidationError, v1.reply, conv, "x", "req-reply-3", reply_to=other_first)


class TestFiles(Base):
    def _send_file(self, conv, token, name, content, **kw):
        as_user("Guest")
        with patch.object(frappe, "request", FakeRequest([(name, content)]), create=True):
            return live_chat.guest_send(conv, token, kw.pop("text", ""), None, None, **kw)

    def test_visitor_attaches_a_photo_and_only_their_chat_can_download_it(self):
        conv, token, first = self.chat()
        out = self._send_file(conv, token, "receipt.png", PNG)
        as_user("Administrator")
        msg = frappe.get_doc(MSG, out["name"])
        self.assertTrue(frappe.db.get_value("File", {"file_url": msg.attachment}, "is_private"))
        view = self.guest_view(conv, token)[msg.name]
        self.assertEqual(view["attachment_kind"], "image")
        as_user("Guest")
        live_chat.guest_attachment(conv, token, msg.name)
        self.assertEqual(frappe.local.response.filecontent, PNG)
        other, other_token, _m = self.chat("someone else")
        as_user("Guest")
        self.assertRaises(Exception, live_chat.guest_attachment, other, other_token, msg.name)
        self.assertRaises(Exception, live_chat.guest_attachment, conv, "wrong-token", msg.name)

    def test_visitor_uploads_follow_the_settings_and_type_rules(self):
        conv, token, first = self.chat()
        self.assertRaises(frappe.ValidationError, self._send_file, conv, token, "tool.exe", b"MZ\x90\x00")
        frappe.db.set_single_value("Support Portal Settings", "allow_guest_uploads", 0)
        frappe.clear_document_cache("Support Portal Settings", "Support Portal Settings")
        from thinknxg_support.utils import clear_request_cache

        clear_request_cache()
        self.assertRaises(frappe.PermissionError, self._send_file, conv, token, "receipt.png", PNG)

    def test_voice_notes_are_checked_audio(self):
        conv, token, first = self.chat()
        out = self._send_file(conv, token, "voice.webm", WEBM, voice_seconds=7)
        as_user("Administrator")
        self.assertEqual(frappe.db.get_value(MSG, out["name"], "voice_seconds"), 7)
        view = self.guest_view(conv, token)[out["name"]]
        self.assertEqual(view["attachment_kind"], "audio")
        self.assertRaises(frappe.ValidationError, self._send_file, conv, token, "voice.webm", b"<script>", voice_seconds=3)
        self.assertRaises(frappe.ValidationError, self._send_file, conv, token, "voice.webm", WEBM, voice_seconds=900)


class TestWhatsApp(Base):
    def _wa_conv(self):
        conv, token, first = self.chat()
        frappe.db.set_value(CONV, conv, {"channel": "WhatsApp", "whatsapp_number": "96891234567",
                                         "whatsapp_window_expires": add_to_date(now_datetime(), hours=2)},
                            update_modified=False)
        frappe.db.set_value(MSG, first, {"channel": "WhatsApp", "external_message_id": "wamid.IN1"},
                            update_modified=False)
        return conv, first

    def test_customer_reactions_and_reply_context_from_whatsapp(self):
        conv, first = self._wa_conv()
        reply = self.agent_says(conv)
        frappe.db.set_value(MSG, reply, "external_message_id", "wamid.OUT1", update_modified=False)
        messaging.whatsapp_reaction("wamid.OUT1", "❤️")
        self.assertEqual(json.loads(frappe.db.get_value(MSG, reply, "reactions_json")), {"❤️": ["c:wa"]})
        messaging.whatsapp_reaction("wamid.OUT1", "")
        self.assertFalse(frappe.db.get_value(MSG, reply, "reactions_json"))
        self.assertEqual(whatsapp.reply_context_of({"context": {"id": "wamid.OUT1"}}), reply)

    def test_agent_media_and_reactions_go_out_through_the_cloud_api(self):
        conv, first = self._wa_conv()
        sent = []

        def fake_send(payload):
            sent.append(payload)
            return f"wamid.X{len(sent)}"

        with patch.object(whatsapp, "available", return_value=True), patch.object(whatsapp, "_send", side_effect=fake_send), \
                patch.object(whatsapp, "_upload_media", return_value="MEDIA1"):
            as_user(self.agent)
            with patch.object(frappe, "request", FakeRequest([("receipt.png", PNG)]), create=True):
                out = v1.reply(conv, "Here is your receipt", "req-wa-1", reply_to=first)
            as_user("Administrator")
            whatsapp.deliver(out["message"]["id"])
            whatsapp.send_reaction(first, "👍")
        image = next(p for p in sent if p.get("type") == "image")
        self.assertEqual(image["image"], {"id": "MEDIA1", "caption": "Here is your receipt"})
        self.assertEqual(image["context"], {"message_id": "wamid.IN1"})
        self.assertEqual(sent[-1]["reaction"], {"message_id": "wamid.IN1", "emoji": "👍"})
        self.assertEqual(frappe.db.get_value(MSG, out["message"]["id"], "delivery_status"), "Sent")
