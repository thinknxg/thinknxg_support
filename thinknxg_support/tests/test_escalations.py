"""Escalated support queries: creation, de-duplication, status sync, overdue, notifications, permissions."""
from unittest.mock import patch

import frappe
from frappe.utils import add_to_date, now_datetime

from thinknxg_support.integrations import escalations, live_chat, routing
from thinknxg_support.integrations.conversations import post_agent_message
from thinknxg_support.tests.utils import BaseTestCase, as_user, make_customer

ESC = "Support Escalation"
CONV = "Support Conversation Link"


def run_now(fn, **kw):
    fn = frappe.get_attr(fn) if isinstance(fn, str) else fn
    return fn(**{k: v for k, v in kw.items() if k not in ("queue", "enqueue_after_commit", "job_id", "deduplicate", "timeout")})


def staff(email, role):
    if not frappe.db.exists("User", email):
        u = frappe.get_doc({"doctype": "User", "email": email, "first_name": email.split("@")[0], "user_type": "System User",
                            "send_welcome_email": 0})
        u.append("roles", {"role": role})
        u.insert(ignore_permissions=True)
    return email


class TestEscalations(BaseTestCase):
    def setUp(self):
        as_user("Administrator")
        self.agent1 = staff("esc-agent1@example.com", "Support Agent")
        self.agent2 = staff("esc-agent2@example.com", "Support Agent")
        self.manager = staff("esc-manager@example.com", "Support Manager")
        if not frappe.db.exists("Support Chat Queue", "Esc Test Team"):
            frappe.get_doc({"doctype": "Support Chat Queue", "queue_name": "Esc Test Team", "enabled": 0, "assignment_rule": "Least Busy",
                            "members": [{"user": self.agent1, "active": 1, "max_chats": 5},
                                        {"user": self.agent2, "active": 1, "max_chats": 5}]}).insert(ignore_permissions=True)
        s = frappe.get_single("Support Escalation Settings")
        s.update({"enabled": 1, "auto_assign": 1, "default_team": "Esc Test Team", "on_chat_handoff": 1,
                  "on_direct_live_chat": 1, "on_conversation_escalation": 1, "on_request_escalation": 1,
                  "notify_in_app": 1, "notify_system": 1, "notify_email": 0, "notify_whatsapp": 0,
                  "notify_roles": "Support Manager", "notify_users": "", "remind_overdue": 1, "overdue_roles": "Support Manager"})
        s.flags.ignore_permissions = True
        s.save()
        frappe.db.set_single_value("Support Portal Settings", {"enable_live_chat": 1, "allow_guest_chat": 1, "enable_raven": 0,
                                                              "guest_chat_rate_limit": 1000})
        frappe.db.set_single_value("Support AI Settings", "enable_ai", 0)
        frappe.db.delete(ESC)
        frappe.cache.delete_keys("thinknxg_support:rl:")
        self.p = patch.object(frappe, "enqueue", side_effect=run_now)
        self.p.start()

    def tearDown(self):
        self.p.stop()
        as_user("Administrator")

    def _settings(self, **values):
        s = frappe.get_single("Support Escalation Settings")
        s.update(values)
        s.flags.ignore_permissions = True
        s.save()

    def _guest_chat(self, email="esc-visitor@example.com"):
        as_user("Guest")
        r = live_chat.start_guest("<p>My invoice is wrong</p>", name="Visitor", email=email)
        as_user("Administrator")
        return r, frappe.get_doc(CONV, r["conversation"])

    def test_direct_live_chat_is_escalated_once_with_details(self):
        r, conv = self._guest_chat()
        rows = frappe.get_all(ESC, filters={"reference_name": conv.name}, fields=["*"])
        self.assertEqual(len(rows), 1)
        e = rows[0]
        self.assertEqual((e.query_type, e.escalation_type), ("Support Chat", "Direct Live Chat"))
        self.assertEqual(e.contact_email, "esc-visitor@example.com")
        self.assertIn("invoice", e.description)
        self.assertTrue(e.response_due and e.resolution_due)
        # the same trigger again changes nothing
        escalations.on_direct_chat(frappe.get_doc(CONV, conv.name))
        self.assertEqual(frappe.db.count(ESC, {"reference_name": conv.name}), 1)
        # the manager role was notified in the notification center
        self.assertTrue(frappe.db.exists("Notification Log", {"for_user": self.manager, "document_type": ESC,
                                                             "document_name": e.name}))

    def test_handoff_kind_and_further_escalation(self):
        self._settings(on_direct_live_chat=0)
        r, conv = self._guest_chat()
        self.assertFalse(frappe.db.exists(ESC, {"reference_name": conv.name}))
        conv.db_set("handling", "Bot")
        routing.handoff(conv, frappe._("Customer asked for a person"), announce=False)
        e = frappe.get_doc(ESC, {"reference_name": conv.name})
        self.assertEqual(e.escalation_type, "Customer Asked for Agent")
        escalations.escalate_further(e, user=self.agent2, priority="Critical", note="VIP customer")
        e.reload()
        self.assertEqual((e.escalation_level, e.priority, e.assigned_to), (2, "Critical", self.agent2))
        self.assertTrue(frappe.db.exists("ToDo", {"reference_type": ESC, "reference_name": e.name, "allocated_to": self.agent2,
                                                  "status": "Open"}))
        self.assertTrue(any(l.action == "Escalated further" for l in e.log))
        # the chat itself moved to that person
        self.assertEqual(frappe.db.get_value(CONV, conv.name, "assigned_agent"), self.agent2)

    def test_reply_progress_close_and_reopen(self):
        r, conv = self._guest_chat()
        as_user(self.agent1)
        post_agent_message(frappe.get_doc(CONV, conv.name), "<p>Looking into it</p>")
        as_user("Administrator")
        e = frappe.get_doc(ESC, {"reference_name": conv.name})
        self.assertEqual(e.status, "In Progress")
        self.assertTrue(e.first_response_on)
        self.assertIsNotNone(e.response_minutes)
        as_user("Guest")
        live_chat.guest_send(r["conversation"], r["token"], "Still wrong")
        as_user("Administrator")
        e.reload()
        self.assertTrue(e.awaiting_reply and e.needs_response)
        live_chat._close(frappe.get_doc(CONV, conv.name))
        e.reload()
        self.assertEqual(e.status, "Resolved")
        self.assertTrue(e.resolved_on)
        escalations.on_activity(CONV, conv.name, "customer_message")
        e.reload()
        self.assertEqual(e.status, "Pending")

    def test_chat_closed_without_reply_stays_open(self):
        r, conv = self._guest_chat()
        live_chat._close(frappe.get_doc(CONV, conv.name))
        e = frappe.get_doc(ESC, {"reference_name": conv.name})
        self.assertIn(e.status, ("New", "Pending"))
        self.assertTrue(e.awaiting_reply)

    def test_overdue_is_flagged_and_alerted_once(self):
        r, conv = self._guest_chat()
        name = frappe.db.get_value(ESC, {"reference_name": conv.name})
        frappe.db.set_value(ESC, name, "response_due", add_to_date(now_datetime(), minutes=-1))
        before = frappe.db.count("Notification Log", {"document_name": name, "for_user": self.manager})
        escalations.check_overdue()
        escalations.check_overdue()
        self.assertEqual(frappe.db.get_value(ESC, name, "overdue"), 1)
        self.assertEqual(frappe.db.count("Notification Log", {"document_name": name, "for_user": self.manager}), before + 1)

    def test_auto_assign_to_least_busy_team_member(self):
        customer = make_customer("Escalation Test LLC")
        req = frappe.get_doc({"doctype": "Support Request", "subject": "Data import stuck", "customer": customer,
                              "raised_by": "Administrator"}).insert(ignore_permissions=True)
        escalations.on_request_escalated(req, None)
        e = frappe.get_doc(ESC, {"reference_name": req.name})
        self.assertEqual(e.query_type, "Support Ticket")
        self.assertIn(e.assigned_to, (self.agent1, self.agent2))
        self.assertEqual(e.status, "Pending")
        req.reload()
        req.status = "Completed"
        req.save(ignore_permissions=True)
        self.assertEqual(frappe.db.get_value(ESC, e.name, "status"), "Resolved")

    def test_payload_has_every_required_field(self):
        r, conv = self._guest_chat()
        e = frappe.get_doc(ESC, {"reference_name": conv.name})
        p = escalations.payload(e, "new")
        for key in ("name", "reference", "customer", "customer_details", "escalation_type", "subject", "escalated_on",
                    "assigned_to", "priority", "url"):
            self.assertTrue(p.get(key), key)
        self.assertIn("/app/support-escalation/", p["url"])

    def test_portal_users_cannot_escalate_or_read(self):
        r, conv = self._guest_chat()
        as_user("Guest")
        with self.assertRaises(frappe.PermissionError):
            escalations.escalate_document(CONV, conv.name, note="x")
        as_user("Administrator")
        self.assertFalse(frappe.has_permission(ESC, "read", user="Guest"))

    def test_disabled_tracking_does_nothing(self):
        self._settings(enabled=0)
        r, conv = self._guest_chat()
        self.assertFalse(frappe.db.exists(ESC, {"reference_name": conv.name}))
