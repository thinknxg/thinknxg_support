"""Staff API v1: who may call it, queue visibility, pagination, read state, atomic claim, idempotent replies,
internal notes staying internal, and Helpdesk tickets (when Helpdesk is installed)."""
from unittest.mock import patch

import frappe

from thinknxg_support.api.staff import v1
from thinknxg_support.api.staff.errors import Conflict
from thinknxg_support.integrations import live_chat
from thinknxg_support.tests.utils import BaseTestCase, as_user

CONV = "Support Conversation Link"
MSG = "Support Portal Message"


def run_now(fn, **kw):
    fn = frappe.get_attr(fn) if isinstance(fn, str) else fn
    return fn(**{k: v for k, v in kw.items() if k not in ("queue", "enqueue_after_commit", "job_id", "deduplicate", "timeout")})


def staff(email, role="Support Agent"):
    if not frappe.db.exists("User", email):
        u = frappe.get_doc({"doctype": "User", "email": email, "first_name": email.split("@")[0], "user_type": "System User",
                            "send_welcome_email": 0})
        u.append("roles", {"role": role})
        u.insert(ignore_permissions=True)
    return email


class TestStaffApi(BaseTestCase):
    def setUp(self):
        as_user("Administrator")
        self.a1 = staff("app-agent1@example.com")
        self.a2 = staff("app-agent2@example.com")
        self.outsider = staff("app-agent3@example.com")
        for q, members in (("App Team", [self.a1, self.a2]), ("Other Team", [self.outsider])):
            if not frappe.db.exists("Support Chat Queue", q):
                frappe.get_doc({"doctype": "Support Chat Queue", "queue_name": q, "enabled": 0, "only_online_agents": 0,
                                "members": [{"user": u, "active": 1, "max_chats": 5} for u in members]}).insert(ignore_permissions=True)
        for single, values in (("Support Escalation Settings", {"enabled": 0}),):
            d = frappe.get_single(single)
            d.update(values)
            d.flags.ignore_permissions = True
            d.save()
        frappe.db.set_single_value("Support Portal Settings", {"enable_live_chat": 1, "allow_guest_chat": 1, "enable_raven": 0,
                                                              "guest_chat_rate_limit": 1000})
        frappe.db.set_single_value("Support AI Settings", "enable_ai", 0)
        frappe.cache.delete_keys("thinknxg_support:rl:")
        self.p = patch.object(frappe, "enqueue", side_effect=run_now)
        self.p.start()

    def tearDown(self):
        self.p.stop()
        as_user("Administrator")

    def _chat(self, queue="App Team", text="<p>My invoice is wrong</p>"):
        as_user("Guest")
        r = live_chat.start_guest(text, name="Visitor", email="app-visitor@example.com")
        as_user("Administrator")
        frappe.db.set_value(CONV, r["conversation"], {"queue": queue, "assigned_agent": None, "handling": "Queued"},
                            update_modified=False)
        return r, r["conversation"]

    def test_customers_and_guests_cannot_use_the_staff_api(self):
        as_user("Guest")
        self.assertRaises(frappe.AuthenticationError, v1.bootstrap)
        cust = "app-customer@example.com"
        as_user("Administrator")
        if not frappe.db.exists("User", cust):
            frappe.get_doc({"doctype": "User", "email": cust, "first_name": "Cust", "user_type": "Website User",
                            "send_welcome_email": 0}).insert(ignore_permissions=True)
        as_user(cust)
        self.assertRaises(frappe.PermissionError, v1.bootstrap)
        self.assertRaises(frappe.PermissionError, v1.conversations)

    def test_bootstrap_identity_and_capabilities(self):
        as_user(self.a1)
        b = v1.bootstrap()
        self.assertEqual(b["agent"]["user"], self.a1)
        self.assertEqual(b["api_version"], 1)
        self.assertIn("helpdesk", b["capabilities"])
        self.assertTrue(any(q["name"] == "App Team" and q["member"] for q in b["queues"]))

    def test_queue_visibility_applies_to_lists_and_lookups(self):
        r, name = self._chat()
        as_user(self.outsider)
        self.assertNotIn(name, [c["id"] for c in v1.conversations(view="all")["items"]])
        self.assertRaises(frappe.PermissionError, v1.conversation, name)
        as_user(self.a1)
        self.assertIn(name, [c["id"] for c in v1.conversations(view="unassigned")["items"]])

    def test_claim_has_one_winner(self):
        r, name = self._chat()
        as_user(self.a1)
        v1.claim(name)
        as_user(self.a2)
        with self.assertRaises(Conflict):
            v1.claim(name)
        as_user("Administrator")
        self.assertEqual(frappe.db.get_value(CONV, name, "assigned_agent"), self.a1)

    def test_reply_is_idempotent_and_customer_sees_it(self):
        r, name = self._chat()
        as_user(self.a1)
        v1.claim(name)
        first = v1.reply(name, "We're on it", client_request_id="11111111-aaaa-bbbb-cccc-000000000001")
        again = v1.reply(name, "We're on it", client_request_id="11111111-aaaa-bbbb-cccc-000000000001")
        self.assertEqual(first["message"]["id"], again["message"]["id"])
        self.assertTrue(again["duplicate"])
        self.assertEqual(frappe.db.count(MSG, {"conversation": name, "client_message_id": "11111111-aaaa-bbbb-cccc-000000000001"}), 1)
        v1.reply(name, "Customer looks upset", client_request_id="11111111-aaaa-bbbb-cccc-000000000002", internal=1)
        as_user("Guest")
        seen = " ".join(m["content"] for m in live_chat.guest_messages(r["conversation"], r["token"])["messages"])
        self.assertIn("on it", seen)
        self.assertNotIn("upset", seen)  # internal note stays staff-only

    def test_pagination_and_read_state(self):
        r, name = self._chat()
        as_user("Guest")
        for i in range(7):
            live_chat.guest_send(r["conversation"], r["token"], f"message {i}")
        as_user(self.a1)
        page1 = v1.messages(name, limit=3)
        self.assertEqual(len(page1["items"]), 3)
        self.assertTrue(page1["has_more_before"])
        page2 = v1.messages(name, before=page1["before_cursor"], limit=3)
        ids1 = {m["id"] for m in page1["items"]}
        self.assertFalse(ids1 & {m["id"] for m in page2["items"]})
        summary = next(c for c in v1.conversations()["items"] if c["id"] == name)
        self.assertEqual(summary["unread"], 8)
        v1.mark_read(name, page1["items"][-1]["id"])
        summary = next(c for c in v1.conversations()["items"] if c["id"] == name)
        self.assertEqual(summary["unread"], 0)
        as_user(self.a2)  # read state is per agent
        self.assertEqual(next(c for c in v1.conversations()["items"] if c["id"] == name)["unread"], 8)

    def test_notification_links_are_checked_again(self):
        r, name = self._chat()
        as_user(self.outsider)
        self.assertRaises(frappe.PermissionError, v1.open_target, CONV, name)
        as_user(self.a1)
        self.assertEqual(v1.open_target(CONV, name), {"kind": "conversation", "id": name})

    def test_helpdesk_ticket_reply_note_and_status(self):
        if not frappe.db.exists("DocType", "HD Ticket"):
            self.skipTest("Helpdesk is not installed")
        from thinknxg_support.integrations import helpdesk_agent

        as_user("Administrator")
        t = frappe.get_doc({"doctype": "HD Ticket", "subject": "App ticket", "raised_by": "app-customer2@example.com",
                            "description": "<p>Printer broken</p>"}).insert(ignore_permissions=True)
        out = v1.ticket_reply(t.name, "We will call you", client_request_id="22222222-aaaa-bbbb-cccc-000000000001")
        again = v1.ticket_reply(t.name, "We will call you", client_request_id="22222222-aaaa-bbbb-cccc-000000000001")
        self.assertFalse(out["duplicate"])
        self.assertTrue(again["duplicate"])
        self.assertEqual(frappe.db.count("Communication", {"reference_doctype": "HD Ticket", "reference_name": t.name,
                                                           "sent_or_received": "Sent"}), 1)
        v1.ticket_note(t.name, "Check warranty", client_request_id="22222222-aaaa-bbbb-cccc-000000000002")
        timeline = v1.ticket_timeline(t.name)["items"]
        self.assertTrue(any(i["internal"] and "warranty" in i["html"] for i in timeline))
        self.assertTrue(any(not i["internal"] and "call you" in i["html"] for i in timeline))
        closed = next((s["name"] for s in helpdesk_agent.statuses() if s["category"] == "Resolved"), None)
        if closed:
            self.assertEqual(v1.ticket_update(t.name, status=closed)["status"], closed)
