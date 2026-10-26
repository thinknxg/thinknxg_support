"""Guest and customer live chat security."""
import frappe

from thinknxg_support.integrations import live_chat
from thinknxg_support.tests.utils import BaseTestCase, as_user


class TestLiveChat(BaseTestCase):
    def setUp(self):
        as_user("Administrator")
        frappe.db.set_single_value("Support Portal Settings", {"enable_live_chat": 1, "allow_guest_chat": 1,
                                                              "enable_raven": 0, "guest_chat_rate_limit": 500})
        frappe.cache.delete_keys("thinknxg_support:rl:")
        as_user("Guest")

    def tearDown(self):
        as_user("Administrator")

    def _start(self, email="visitor@example.com"):
        return live_chat.start_guest("<p>Hello</p>", name="Visitor One", email=email)

    def test_guest_start_and_read_with_token(self):
        r = self._start()
        self.assertTrue(r["token"])
        stored = frappe.db.get_value("Support Conversation Link", r["conversation"], "guest_token_hash")
        self.assertNotEqual(stored, r["token"])  # only the hash is stored
        data = live_chat.guest_messages(r["conversation"], r["token"])
        self.assertEqual(len(data["messages"]), 1)
        self.assertNotIn("<script", data["messages"][0]["content"])

    def test_wrong_or_foreign_token_is_rejected(self):
        a = self._start("a@example.com")
        b = self._start("b@example.com")
        with self.assertRaises(frappe.PermissionError):
            live_chat.guest_messages(a["conversation"], "not-the-token")
        with self.assertRaises(frappe.PermissionError):
            live_chat.guest_messages(a["conversation"], b["token"])
        with self.assertRaises(frappe.PermissionError):
            live_chat.guest_send(b["conversation"], a["token"], "hi")

    def test_guest_html_is_escaped(self):
        r = live_chat.start_guest("<img src=x onerror=alert(1)>", name="Eve", email="eve@example.com")
        content = live_chat.guest_messages(r["conversation"], r["token"])["messages"][0]["content"]
        self.assertNotIn("<img", content)

    def test_internal_notes_hidden_from_guest(self):
        r = self._start()
        as_user("Administrator")
        from thinknxg_support.integrations.conversations import post_agent_message

        conv = frappe.get_doc("Support Conversation Link", r["conversation"])
        post_agent_message(conv, "secret internal", internal=1)
        post_agent_message(conv, "<p>Visible</p>")
        as_user("Guest")
        texts = " ".join(m["content"] for m in live_chat.guest_messages(r["conversation"], r["token"])["messages"])
        self.assertNotIn("secret internal", texts)
        self.assertIn("Visible", texts)

    def test_closed_chat_rejects_messages(self):
        r = self._start()
        live_chat.guest_end(r["conversation"], r["token"], rating=4)
        with self.assertRaises(frappe.ValidationError):
            live_chat.guest_send(r["conversation"], r["token"], "still there?")
        self.assertAlmostEqual(frappe.db.get_value("Support Conversation Link", r["conversation"], "chat_rating"), 0.8)

    def test_guest_disabled(self):
        as_user("Administrator")
        frappe.db.set_single_value("Support Portal Settings", "allow_guest_chat", 0)
        as_user("Guest")
        self.assertEqual(live_chat.chat_mode()[0], "login")
        with self.assertRaises(frappe.PermissionError):
            self._start()

    def test_invalid_email_rejected(self):
        with self.assertRaises(frappe.ValidationError):
            live_chat.start_guest("hi", name="X Y", email="not-an-email")

    def test_guest_chat_never_linked_to_customer(self):
        r = self._start()
        self.assertFalse(frappe.db.get_value("Support Conversation Link", r["conversation"], "customer"))

    def test_business_hours(self):
        from frappe.utils import get_datetime

        as_user("Administrator")
        frappe.db.set_single_value("Support Portal Settings", {"chat_days": "Sun,Mon,Tue,Wed,Thu",
                                                              "chat_start_time": "08:00:00", "chat_end_time": "17:00:00"})
        from thinknxg_support.utils import clear_request_cache

        clear_request_cache()
        self.assertTrue(live_chat.is_online(get_datetime("2026-10-25 10:00:00")))   # Sunday
        self.assertFalse(live_chat.is_online(get_datetime("2026-10-23 10:00:00")))  # Friday
        self.assertFalse(live_chat.is_online(get_datetime("2026-10-25 18:30:00")))
