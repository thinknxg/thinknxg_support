"""Canned responses, chat wrap-up, and the agent alert centre (who is alerted, what stops it, acknowledgement)."""
from unittest.mock import patch

import frappe
from frappe.utils import add_to_date, now_datetime

from thinknxg_support.integrations import agent_tools, alerts, live_chat, routing
from thinknxg_support.integrations.conversations import post_agent_message
from thinknxg_support.tests.utils import BaseTestCase, as_user

CONV = "Support Conversation Link"
ALERT = "Support Agent Alert"


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


class TestAgentTools(BaseTestCase):
    def setUp(self):
        as_user("Administrator")
        self.a1 = staff("tools-agent1@example.com")
        self.a2 = staff("tools-agent2@example.com")
        if not frappe.db.exists("Support Chat Queue", "Tools Team"):
            frappe.get_doc({"doctype": "Support Chat Queue", "queue_name": "Tools Team", "enabled": 0, "only_online_agents": 0,
                            "assignment_rule": "Least Busy",
                            "members": [{"user": self.a1, "active": 1, "max_chats": 5},
                                        {"user": self.a2, "active": 1, "max_chats": 5}]}).insert(ignore_permissions=True)
        s = frappe.get_single("Support Escalation Settings")
        s.enabled = 0
        s.flags.ignore_permissions = True
        s.save()
        frappe.db.set_single_value("Support Portal Settings", {"enable_live_chat": 1, "allow_guest_chat": 1, "enable_raven": 0,
                                                              "guest_chat_rate_limit": 1000, "require_closure_reason": 1,
                                                              "chat_closing_message": "Thanks for chatting with us."})
        frappe.db.set_single_value("Support AI Settings", "enable_ai", 0)
        from thinknxg_support.install import ensure_agent_tool_defaults

        ensure_agent_tool_defaults()
        frappe.db.delete(ALERT)
        frappe.cache.delete_keys("thinknxg_support:rl:")
        self.p = patch.object(frappe, "enqueue", side_effect=run_now)
        self.p.start()

    def tearDown(self):
        self.p.stop()
        as_user("Administrator")

    def _chat(self):
        as_user("Guest")
        r = live_chat.start_guest("<p>Where is my order?</p>", name="Visitor", email="tools-visitor@example.com")
        as_user("Administrator")
        conv = frappe.get_doc(CONV, r["conversation"])
        conv.db_set({"queue": "Tools Team", "assigned_agent": None}, update_modified=False)
        return r, conv

    # ---------------------------------------------------------------- canned responses
    def test_private_canned_responses_stay_private(self):
        as_user(self.a1)
        frappe.get_doc({"doctype": "Support Canned Response", "title": "My signature", "shortcut": "sig1",
                        "visibility": "Only Me", "content": "<p>Regards, {agent_first_name}</p>"}).insert()
        as_user(self.a2)
        self.assertNotIn("My signature", [r["title"] for r in agent_tools.canned_responses()])
        as_user(self.a1)
        self.assertIn("My signature", [r["title"] for r in agent_tools.canned_responses()])

    def test_shortcut_rules(self):
        frappe.get_doc({"doctype": "Support Canned Response", "title": "Refund policy", "shortcut": "/Refund",
                        "content": "<p>Refunds take 5 days.</p>"}).insert(ignore_permissions=True)
        self.assertEqual(frappe.db.get_value("Support Canned Response", {"title": "Refund policy"}, "shortcut"), "refund")
        with self.assertRaises(frappe.ValidationError):
            frappe.get_doc({"doctype": "Support Canned Response", "title": "Other refund", "shortcut": "refund",
                            "content": "<p>x</p>"}).insert(ignore_permissions=True)
        with self.assertRaises(frappe.ValidationError):
            frappe.get_doc({"doctype": "Support Canned Response", "title": "Bad", "shortcut": "two words",
                            "content": "<p>x</p>"}).insert(ignore_permissions=True)

    # ---------------------------------------------------------------- wrap-up
    def test_end_chat_records_wrap_up(self):
        r, conv = self._chat()
        form = agent_tools.closing_form()
        q_required = next(q for q in form["questions"] if q["required"])
        with self.assertRaises(frappe.ValidationError):
            agent_tools.end_chat(conv.name, reason="", notes="x")  # reason required
        with self.assertRaises(frappe.ValidationError):
            agent_tools.end_chat(conv.name, reason="Resolved", answers={})  # required question unanswered
        agent_tools.end_chat(conv.name, reason="Resolved", notes="Sent tracking link",
                             answers={str(q_required["idx"]): "Yes"})
        conv.reload()
        self.assertEqual((conv.status, conv.closure_reason, conv.closure_notes), ("Closed", "Resolved", "Sent tracking link"))
        self.assertEqual(conv.wrap_up_answers[0].answer, "Yes")
        notes = frappe.get_all("Support Portal Message", filters={"conversation": conv.name, "is_internal": 1}, pluck="content")
        self.assertTrue(any("Sent tracking link" in (n or "") for n in notes))
        as_user("Guest")
        seen = " ".join(m["content"] for m in live_chat.guest_messages(r["conversation"], r["token"])["messages"])
        self.assertNotIn("Sent tracking link", seen)  # the wrap-up stays internal
        self.assertIn("Thanks for chatting", seen)

    # ---------------------------------------------------------------- alerts
    def test_new_chat_rings_queue_until_assigned(self):
        r, conv = self._chat()
        alerts.on_new_chat(conv)
        for u in (self.a1, self.a2):
            self.assertTrue(frappe.db.exists(ALERT, {"user": u, "group_key": f"chat:{conv.name}", "status": "Open"}))
        alerts.on_new_chat(conv)  # no duplicate while open
        self.assertEqual(frappe.db.count(ALERT, {"user": self.a1, "group_key": f"chat:{conv.name}"}), 1)
        routing.assign(frappe.get_doc(CONV, conv.name), self.a2, "Tools Team", "Manual")
        self.assertEqual(frappe.db.get_value(ALERT, {"user": self.a1, "group_key": f"chat:{conv.name}"}, "status"), "Handled")
        self.assertEqual(frappe.db.get_value(ALERT, {"user": self.a2, "group_key": f"chat:{conv.name}"}, "status"), "Open")
        as_user(self.a2)
        post_agent_message(frappe.get_doc(CONV, conv.name), "<p>On it</p>")
        as_user("Administrator")
        self.assertFalse(frappe.db.exists(ALERT, {"group_key": f"chat:{conv.name}", "status": "Open"}))

    def test_acknowledge_only_own_and_timed(self):
        r, conv = self._chat()
        alerts.on_new_chat(conv)
        mine = frappe.db.get_value(ALERT, {"user": self.a1, "group_key": f"chat:{conv.name}"})
        theirs = frappe.db.get_value(ALERT, {"user": self.a2, "group_key": f"chat:{conv.name}"})
        as_user(self.a1)
        self.assertEqual(alerts.acknowledge([mine, theirs]), [mine])
        as_user("Administrator")
        row = frappe.db.get_value(ALERT, mine, ["status", "ack_seconds"], as_dict=True)
        self.assertEqual(row.status, "Acknowledged")
        self.assertIsNotNone(row.ack_seconds)
        self.assertEqual(frappe.db.get_value(ALERT, theirs, "status"), "Open")

    def test_message_alerts_are_not_stored_and_disabled_rules_are_silent(self):
        r, conv = self._chat()
        conv.db_set({"handling": "Agent", "assigned_agent": self.a1}, update_modified=False)
        alerts.on_customer_message(frappe.get_doc(CONV, conv.name))
        self.assertFalse(frappe.db.exists(ALERT, {"group_key": f"msg:{conv.name}"}))
        s = frappe.get_single("Support Alert Settings")
        for row in s.rules:
            if row.kind == "New Chat":
                row.enabled = 0
        s.flags.ignore_permissions = True
        s.save()
        alerts.on_new_chat(frappe.get_doc(CONV, conv.name))
        self.assertFalse(frappe.db.exists(ALERT, {"group_key": f"chat:{conv.name}"}))

    def test_preferences_and_config(self):
        as_user(self.a1)
        name = alerts.open_my_preferences()
        pref = frappe.get_doc("Support Alert Preference", name)
        self.assertEqual(pref.user, self.a1)
        self.assertEqual({i.kind for i in pref.items}, set(alerts.KINDS))
        pref.volume = 140
        pref.items[0].sound = "None"
        pref.save()
        cfg = alerts.config()
        self.assertEqual(cfg["prefs"]["volume"], 100)
        self.assertEqual(cfg["prefs"]["items"][pref.items[0].kind]["sound"], "None")
        as_user(self.a2)
        with self.assertRaises(frappe.PermissionError):
            other = frappe.get_doc("Support Alert Preference", name)
            other.mute_all = 1
            other.save()

    def test_unacknowledged_alerts_expire(self):
        r, conv = self._chat()
        alerts.on_new_chat(conv)
        frappe.db.set_value(ALERT, {"user": self.a1, "group_key": f"chat:{conv.name}"}, "alerted_on",
                            add_to_date(now_datetime(), hours=-30))
        alerts.expire_and_purge()
        self.assertEqual(frappe.db.get_value(ALERT, {"user": self.a1, "group_key": f"chat:{conv.name}"}, "status"), "Expired")

    def test_portal_users_get_no_alert_config(self):
        as_user("Guest")
        self.assertEqual(alerts.config(), {"enabled": False})
        self.assertEqual(alerts.my_alerts(), [])
