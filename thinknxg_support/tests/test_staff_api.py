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

    def test_oauth_client_redirects_pass_frappes_own_check(self):
        from frappe.oauth import OAuthWebRequestValidator

        from thinknxg_support.integrations import staff_auth

        as_user("Administrator")
        # a site whose settings were never saved: the sign-in address fields are empty
        frappe.db.set_single_value("Support Agent App Settings", {"desktop_redirect_uri": "", "mobile_redirect_uri": ""})
        frappe.clear_document_cache("Support Agent App Settings", "Support Agent App Settings")
        self.assertIn("http://127.0.0.1:43823/callback", staff_auth.redirect_uris())
        client_id = staff_auth.ensure_oauth_client(force=True)["client_id"]
        self.assertEqual(frappe.db.get_single_value("Support Agent App Settings", "desktop_redirect_uri"),
                         "http://127.0.0.1:43823/callback")
        v = OAuthWebRequestValidator()
        for uri in staff_auth.redirect_uris():
            self.assertTrue(v.validate_redirect_uri(client_id, uri, None), uri)
        self.assertFalse(v.validate_redirect_uri(client_id, "http://127.0.0.1:9999/evil", None))
        cfg = v1.auth_config()
        self.assertEqual(cfg["client_id"], client_id)
        # what the app checks is exactly what Frappe accepts
        self.assertEqual(set(cfg["redirect_uris"]), {"http://127.0.0.1:43823/callback", "com.thinknxg.agent://oauth2redirect"})

    # ------------------------------------------------------------------ helpdesk enhancements (1.9)
    def test_live_chat_message_without_queue_rings_every_agent(self):
        from thinknxg_support.integrations import alerts

        r, name = self._chat(queue=None)
        frappe.db.set_value(CONV, name, "handling", "Agent", update_modified=False)
        as_user(self.a1)
        cursor = v1.alerts()["cursor"]
        as_user("Administrator")
        rules = {"Chat Message": {**alerts.DEFAULTS["Chat Message"], "enabled": 1}}
        with patch.object(alerts, "rules", return_value=rules):
            alerts.on_customer_message(frappe.get_doc(CONV, name))
        as_user(self.a1)
        self.assertIn(name, [e["reference_name"] for e in v1.alerts(since=cursor)["events"]])

    def test_link_customer_registers_hd_customer_with_the_visitor_contact(self):
        if not frappe.db.exists("DocType", "HD Customer"):
            self.skipTest("Helpdesk is not installed")
        from thinknxg_support.tests.utils import make_customer

        customer = make_customer("App Link Customer")
        hd = frappe.db.get_value("HD Customer", {"erpnext_customer": customer}) if frappe.get_meta("HD Customer").has_field(
            "erpnext_customer") else frappe.db.exists("HD Customer", "App Link Customer")
        self.assertTrue(hd, "a new Customer is registered as an HD Customer")
        r, name = self._chat()
        as_user(self.a1)
        self.assertTrue(any(c["name"] == customer for c in v1.customer_search("App Link")))
        out = v1.link_customer(name, customer, create_contact=1)
        self.assertEqual(out["customer"], customer)
        contact = frappe.db.get_value(CONV, name, "contact")
        self.assertTrue(contact)
        self.assertEqual(frappe.db.get_value("Contact", contact, "email_id"), "app-visitor@example.com")
        self.assertTrue(frappe.db.exists("Dynamic Link", {"parenttype": "Contact", "parent": contact,
                                                          "link_doctype": "HD Customer", "link_name": hd}))
        self.assertIn(contact, [c["name"] for c in v1.customer_contacts(customer)])

    def test_create_ticket_from_chat_with_a_saved_reply(self):
        if not frappe.db.exists("DocType", "HD Ticket"):
            self.skipTest("Helpdesk is not installed")
        self._ensure_outgoing_email()
        frappe.db.set_single_value("Support Portal Settings", "enable_helpdesk", 1)
        from thinknxg_support.integrations import capabilities

        if hasattr(capabilities, "refresh"):
            capabilities.refresh()
        r, name = self._chat()
        as_user("Administrator")  # a Helpdesk agent
        frappe.db.set_value(CONV, name, "assigned_agent", "Administrator", update_modified=False)
        sr_dt = "HD Saved Reply" if frappe.db.exists("DocType", "HD Saved Reply") else None
        reply = "We are on it"
        if sr_dt:
            sr = frappe.get_doc({"doctype": sr_dt, "title": "App on it", "message": "<p>Hello, {{ full_name }} is on it</p>"})
            if sr.meta.has_field("scope"):
                sr.scope = "Global"
            sr.insert(ignore_permissions=True)
            self.assertIn(sr.name, [x["name"] for x in v1.saved_replies("App on")])
            reply = v1.saved_reply_render(sr.name, conversation=name)["text"]
            self.assertIn("Administrator is on it", reply)
        opts = v1.ticket_options()
        out = v1.create_ticket(name, client_request_id="44444444-aaaa-bbbb-cccc-000000000001", subject="Invoice wrong",
                               priority=(opts["priorities"] or [None])[0], reply=reply)
        again = v1.create_ticket(name, client_request_id="44444444-aaaa-bbbb-cccc-000000000001")
        self.assertEqual(out["ticket"], again["ticket"])
        self.assertEqual(frappe.db.get_value(CONV, name, "helpdesk_ticket"), out["ticket"])
        self.assertEqual(frappe.db.get_value("HD Ticket", out["ticket"], "subject"), "Invoice wrong")
        self.assertEqual(frappe.db.get_value("HD Ticket", out["ticket"], "raised_by"), "app-visitor@example.com")
        if sr_dt:
            rendered = v1.saved_reply_render(sr.name, ticket=out["ticket"])["text"]
            self.assertIn("is on it", rendered)

    def test_end_chat_asks_resolution_and_follow_up(self):
        r, name = self._chat()
        as_user(self.a1)
        v1.claim(name)
        form = v1.closing_form()
        keys = {q.get("report_as"): q for q in form["questions"]}
        self.assertEqual(keys["Issue Resolved"]["options"], ["Yes", "No"])
        self.assertTrue(keys["Follow-up Needed"]["required"])
        answers = {str(q["idx"]): (q["options"] or ["x"])[0] for q in form["questions"] if q["required"]}
        answers[str(keys["Issue Resolved"]["idx"])] = "No"
        answers[str(keys["Follow-up Needed"]["idx"])] = "Yes"
        v1.close(name, reason=(form["reasons"] or [None])[0], answers=answers)
        self.assertEqual(frappe.db.get_value(CONV, name, ["issue_resolved", "needs_follow_up"]), ("No", "Yes"))

    def _ensure_outgoing_email(self):
        if not frappe.db.exists("Email Account", {"default_outgoing": 1, "enable_outgoing": 1}):
            ea = frappe.get_doc({"doctype": "Email Account", "email_account_name": "App Test Outgoing",
                                 "email_id": "support@example.com", "enable_outgoing": 1, "default_outgoing": 1,
                                 "smtp_server": "localhost", "awaiting_password": 1})
            ea.flags.ignore_validate = True
            ea.flags.ignore_mandatory = True
            ea.insert(ignore_permissions=True)

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

    def test_whatsapp_attachments_are_queued_for_sending(self):
        """1.14: files go out through the WhatsApp Cloud API (until 1.13 they were refused with a reason)."""
        r, name = self._chat()
        frappe.db.set_value(CONV, name, {"channel": "WhatsApp", "whatsapp_number": "96890000000",
                                         "whatsapp_window_expires": frappe.utils.add_to_date(None, hours=5)},
                            update_modified=False)
        as_user(self.a1)
        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
        with patch("thinknxg_support.utils.uploaded_files", return_value=[("a.png", png)]):
            out = v1.reply(name, "file", client_request_id="33333333-aaaa-bbbb-cccc-000000000002")
        self.assertEqual(out["message"]["attachment_kind"], "image")
        # accepted and handed to WhatsApp (switched off in this test, so the delivery itself fails with that reason)
        self.assertIn("not enabled", out["message"]["delivery"]["error"] or "WhatsApp is not enabled")

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

    def test_pushes_are_tracked_retried_and_carry_the_badge(self):
        from frappe.utils import add_to_date, now_datetime

        from thinknxg_support.integrations import push

        DELIVERY = "Support Push Delivery"
        frappe.db.delete(DELIVERY)
        frappe.db.delete("Support Agent Device", {"user": self.a1})
        as_user(self.a1)
        v1.register_device("tok-mac-1", "macOS", "MacBook")
        as_user("Administrator")
        s = frappe.get_single("Support Agent App Settings")
        s.update({"push_enabled": 1, "fcm_project_id": "demo-project"})
        s.flags.ignore_permissions = True
        s.save()
        sent = []

        class Down:
            status_code = 503
            text = "unavailable"

        class Ok:
            status_code = 200
            text = "{}"

        def post(url, headers=None, json=None, timeout=None):
            sent.append(json["message"])
            return Down() if len(sent) == 1 else Ok()

        with patch.object(push, "access_token", return_value="x"), patch("requests.post", side_effect=post), \
                patch.object(push, "badge_for", return_value=3):
            out = push.deliver([self.a1], {"doctype": CONV, "name": "X2", "kind": "New Chat"})
            self.assertEqual(out["retrying"], 1)
            row = frappe.get_all(DELIVERY, filters={"user": self.a1}, fields=["name", "status", "attempts", "next_attempt"])[0]
            self.assertEqual((row.status, row.attempts), ("Retrying", 1))
            push.retry_due()  # not due yet
            self.assertEqual(len(sent), 1)
            frappe.db.set_value(DELIVERY, row.name, "next_attempt", add_to_date(now_datetime(), seconds=-5))
            push.retry_due()
        row = frappe.db.get_value(DELIVERY, row.name, ["status", "attempts", "platform"], as_dict=True)
        self.assertEqual((row.status, row.attempts, row.platform), ("Sent", 2, "macOS"))
        m = sent[-1]
        self.assertEqual(m["apns"]["payload"]["aps"]["badge"], 3)
        self.assertEqual(m["android"]["notification"]["notification_count"], 3)
        delivery = m["data"]["delivery"]
        as_user(self.a2)
        self.assertFalse(v1.push_opened(delivery)["ok"])  # only the agent it was sent to
        as_user(self.a1)
        self.assertTrue(v1.push_opened(delivery)["ok"])
        as_user("Administrator")
        self.assertEqual(frappe.db.get_value(DELIVERY, delivery, "status"), "Opened")
        frappe.db.set_value(DELIVERY, delivery, "creation", add_to_date(now_datetime(), days=-20))
        push.purge()
        self.assertFalse(frappe.db.exists(DELIVERY, delivery))
        s.push_enabled = 0
        s.save()

    def test_copilot_endpoint_returns_drafts_only(self):
        from thinknxg_support.integrations.ai import providers

        frappe.db.set_single_value("Support AI Settings", {"enable_copilot": 1, "provider": "OpenAI Compatible",
                                                           "api_base_url": "https://ai.example.com/v1", "daily_token_budget": 0})
        frappe.clear_document_cache("Support AI Settings", "Support AI Settings")
        r, name = self._chat()
        before = frappe.db.count(MSG, {"conversation": name})
        as_user(self.a1)
        fake = {"text": '[{"label": "Apologise", "text": "Sorry about that."}]', "provider": "Fake", "model": "f"}
        with patch.object(providers, "complete", return_value=fake):
            out = v1.copilot(name, "suggest")
        self.assertEqual(out["suggestions"][0]["text"], "Sorry about that.")
        self.assertEqual(frappe.db.count(MSG, {"conversation": name}), before)  # nothing sent
        self.assertIn("insight", v1.conversation(name))
        as_user(self.outsider)
        self.assertRaises(frappe.PermissionError, v1.copilot, name, "suggest")

    def test_unstored_alerts_reach_the_apps(self):
        from thinknxg_support.integrations import alerts

        r, name = self._chat()
        as_user(self.a1)
        first = v1.alerts()
        self.assertEqual(first["events"], [])  # opening the app does not replay sounds
        as_user("Administrator")
        rules = {"Chat Message": {**alerts.DEFAULTS["Chat Message"], "enabled": 1}}
        with patch.object(alerts, "rules", return_value=rules):
            alerts.raise_alert("Chat Message", [self.a1], "New message", reference_doctype=CONV, reference_name=name,
                               group_key=f"msg:{name}")
        as_user(self.a1)
        nxt = v1.alerts(since=first["cursor"])
        self.assertEqual([e["kind"] for e in nxt["events"]], ["Chat Message"])
        self.assertEqual(v1.alerts(since=nxt["cursor"])["events"], [])  # each event once
        as_user(self.a2)
        self.assertFalse([e for e in v1.alerts(since=0)["events"] if e["title"] == "New message"])  # only for a1

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
