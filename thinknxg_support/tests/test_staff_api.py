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


ENQUEUE_ARGS = ("queue", "enqueue_after_commit", "job_id", "deduplicate", "timeout", "now", "at_front", "job_name",
                "is_async", "event", "on_success", "on_failure")


def run_now(fn, **kw):
    fn = frappe.get_attr(fn) if isinstance(fn, str) else fn
    return fn(**{k: v for k, v in kw.items() if k not in ENQUEUE_ARGS})


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
        if not frappe.db.exists("Email Account", {"default_outgoing": 1, "enable_outgoing": 1}):
            ea = frappe.get_doc({"doctype": "Email Account", "email_account_name": "App Test Outgoing",
                                 "email_id": "support@example.com", "enable_outgoing": 1, "default_outgoing": 1,
                                 "smtp_server": "localhost", "awaiting_password": 1})
            ea.flags.ignore_validate = True
            ea.flags.ignore_mandatory = True
            ea.insert(ignore_permissions=True)
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

    # ------------------------------------------------------------------ increment 2: workspace
    def test_canned_response_placeholders_are_filled(self):
        r, name = self._chat()
        as_user(self.a1)
        c = frappe.get_doc({"doctype": "Support Canned Response", "title": "Hello app", "shortcut": "helloapp",
                            "visibility": "Team", "content": "<p>Hi {customer_first_name}, {agent_first_name} here.</p>"}).insert()
        out = v1.canned_render(c.name, name)
        self.assertIn("Hi Visitor, app-agent1 here.", out["text"])
        self.assertEqual(frappe.db.get_value("Support Canned Response", c.name, "usage_count"), 1)

    def test_attachment_upload_and_authorised_download(self):
        r, name = self._chat()
        as_user(self.a1)
        v1.claim(name)
        import io

        from pypdf import PdfWriter  # Frappe v16 checks that a PDF really is one

        w, buf = PdfWriter(), io.BytesIO()
        w.add_blank_page(width=72, height=72)
        w.write(buf)
        with patch("thinknxg_support.utils.uploaded_files", return_value=[("invoice.pdf", buf.getvalue())]):
            out = v1.reply(name, "Here is your invoice", client_request_id="33333333-aaaa-bbbb-cccc-000000000001")
        self.assertEqual(out["message"]["attachment"]["name"], "invoice.pdf")
        msg = out["message"]["id"]
        self.assertTrue(frappe.db.get_value("File", {"attached_to_doctype": MSG, "attached_to_name": msg}, "is_private"))
        v1.attachment(msg)
        self.assertEqual(frappe.local.response.filename, "invoice.pdf")
        as_user(self.outsider)
        self.assertRaises(frappe.PermissionError, v1.attachment, msg)

    def test_whatsapp_attachments_are_refused_with_a_reason(self):
        r, name = self._chat()
        frappe.db.set_value(CONV, name, {"channel": "WhatsApp", "whatsapp_number": "96890000000",
                                         "whatsapp_window_expires": frappe.utils.add_to_date(None, hours=5)},
                            update_modified=False)
        as_user(self.a1)
        from thinknxg_support.api.staff.errors import ChannelActionRequired

        with patch("thinknxg_support.utils.uploaded_files", return_value=[("a.pdf", b"%PDF-1.4")]):
            with self.assertRaises(ChannelActionRequired):
                v1.reply(name, "file", client_request_id="33333333-aaaa-bbbb-cccc-000000000002")

    def test_transfer_targets_and_customer_history(self):
        r1, first = self._chat()
        r2, second = self._chat()
        as_user(self.a1)
        t = v1.transfer_targets(second)
        users = [a["user"] for a in t["agents"]]
        self.assertIn(self.a2, users)
        self.assertNotIn(self.a1, users)
        self.assertTrue(next(a for a in t["agents"] if a["user"] == self.a2)["in_queue"])
        h = v1.customer_history(second)
        self.assertIn(first, [c["id"] for c in h["conversations"]])  # same guest e-mail
        self.assertNotIn(second, [c["id"] for c in h["conversations"]])
        frappe.db.set_value(CONV, first, "queue", "Other Team", update_modified=False)
        self.assertNotIn(first, [c["id"] for c in v1.customer_history(second)["conversations"]])  # not visible to a1

    def test_typing_and_live_state(self):
        r, name = self._chat()
        as_user(self.a1)
        v1.typing(name)
        from thinknxg_support.integrations import realtime

        self.assertTrue(realtime.is_online(self.a1))
        self.assertIn("customer_typing", v1.live(name))

    # ------------------------------------------------------------------ increment 3: push
    def test_push_text_is_generic_and_dead_tokens_are_dropped(self):
        from thinknxg_support.integrations import push

        m = push.message_for("tok", {"doctype": CONV, "name": "X1", "kind": "New Chat", "title": "secret customer"}, "Android")
        self.assertEqual(m["notification"], {"title": "thinkNXG Support", "body": "New support activity"})
        self.assertNotIn("title", m["data"])  # only routing keys travel
        as_user(self.a1)
        v1.register_device("tok-123", "Android", "Pixel")
        as_user("Administrator")
        s = frappe.get_single("Support Agent App Settings")
        s.update({"push_enabled": 1, "fcm_project_id": "demo-project"})
        s.flags.ignore_permissions = True
        s.save()

        class R:
            status_code = 404
            text = '{"error": {"status": "NOT_FOUND", "details": [{"errorCode": "UNREGISTERED"}]}}'

        with patch.object(push, "access_token", return_value="x"), patch("requests.post", return_value=R()):
            out = push.deliver([self.a1], {"doctype": CONV, "name": "X1"})
        self.assertEqual(out["removed"], 1)
        self.assertEqual(frappe.db.get_value("Support Agent Device", {"user": self.a1}, "enabled"), 0)
        s.push_enabled = 0
        s.save()

    def test_alerts_trigger_a_push(self):
        from thinknxg_support.integrations import alerts, push

        r, name = self._chat()
        rules = {"New Chat": {**alerts.DEFAULTS["New Chat"], "enabled": 1}}
        with patch.object(alerts, "rules", return_value=rules), patch.object(push, "enabled", return_value=True), \
                patch.object(push, "send_to_users") as sent:
            alerts.raise_alert("New Chat", [self.a1], "New chat", reference_doctype=CONV, reference_name=name,
                               group_key=f"apptest:{name}")
        sent.assert_called_once()
        self.assertEqual(sent.call_args[0][1], {"kind": "New Chat", "doctype": CONV, "name": name})
