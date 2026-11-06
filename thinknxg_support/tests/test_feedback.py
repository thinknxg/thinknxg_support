"""Post-chat feedback: validation, link to chat and agent, one per chat, alerts, link tokens, permissions, report."""
from unittest.mock import patch

import frappe

from thinknxg_support.integrations import alerts, feedback, live_chat
from thinknxg_support.tests.utils import BaseTestCase, as_user

CONV = "Support Conversation Link"
FB = "Support Chat Feedback"
ALERT = "Support Agent Alert"


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


class TestFeedback(BaseTestCase):
    def setUp(self):
        as_user("Administrator")
        self.agent = staff("fb-agent@example.com", "Support Agent")
        self.other = staff("fb-other@example.com", "Support Agent")
        self.manager = staff("fb-manager@example.com", "Support Manager")
        frappe.db.set_single_value("Support Portal Settings", {
            "enable_live_chat": 1, "allow_guest_chat": 1, "enable_raven": 0, "guest_chat_rate_limit": 1000,
            "survey_mode": "Optional", "survey_ask_resolution": 1, "survey_ask_comment": 1, "survey_comment_required_at": 2,
            "negative_feedback_at": 2, "negative_feedback_roles": "Support Manager", "notify_agent_positive": 1})
        frappe.db.set_single_value("Support AI Settings", "enable_ai", 0)
        s = frappe.get_single("Support Escalation Settings")
        s.enabled = 0
        s.flags.ignore_permissions = True
        s.save()
        from thinknxg_support.install import ensure_agent_tool_defaults

        ensure_agent_tool_defaults()
        frappe.db.delete(FB)
        frappe.db.delete(ALERT)
        frappe.cache.delete_keys("thinknxg_support:rl:")
        from thinknxg_support.utils import clear_request_cache

        clear_request_cache()
        self.p = patch.object(frappe, "enqueue", side_effect=run_now)
        self.p.start()

    def tearDown(self):
        self.p.stop()
        as_user("Administrator")

    def _chat(self):
        as_user("Guest")
        r = live_chat.start_guest("<p>Card declined</p>", name="Mona", email="fb-visitor@example.com")
        as_user("Administrator")
        frappe.db.set_value(CONV, r["conversation"], {"assigned_agent": self.agent, "handling": "Agent"})
        return r

    def test_rating_resolution_comment_rules(self):
        r = self._chat()
        conv = frappe.get_doc(CONV, r["conversation"])
        with self.assertRaises(frappe.ValidationError):
            feedback.submit(conv, 6, "Yes")
        with self.assertRaises(frappe.ValidationError):
            feedback.submit(conv, 4)  # resolution asked
        with self.assertRaises(frappe.ValidationError):
            feedback.submit(conv, 1, "No")  # low rating needs a comment
        feedback.submit(conv, 1, "No", "Nobody answered for 20 minutes")
        fb = frappe.get_doc(FB, {"conversation": conv.name})
        self.assertEqual((fb.agent, fb.rating, fb.sentiment, fb.rating_label), (self.agent, 1, "Negative", "Very Poor"))
        self.assertEqual(frappe.db.get_value(CONV, conv.name, "status"), "Closed")
        self.assertEqual(frappe.db.get_value(CONV, conv.name, "feedback"), fb.name)

    def test_one_feedback_per_chat_and_alerts(self):
        r = self._chat()
        as_user("Guest")
        live_chat.guest_survey(r["conversation"], r["token"], 5, "Yes", "Quick and kind")
        as_user("Administrator")
        self.assertTrue(frappe.db.exists(FB, {"conversation": r["conversation"], "sentiment": "Positive"}))
        self.assertEqual(frappe.db.count(FB, {"conversation": r["conversation"]}), 1)
        as_user("Guest")
        live_chat.guest_survey(r["conversation"], r["token"], 2, "Partially", "Actually it broke again")
        as_user("Administrator")
        self.assertEqual(frappe.db.count(FB, {"conversation": r["conversation"]}), 1)
        self.assertEqual(frappe.db.get_value(FB, {"conversation": r["conversation"]}, "sentiment"), "Negative")
        self.assertTrue(frappe.db.exists(ALERT, {"user": self.manager, "kind": "Negative Feedback"}))

    def test_link_token(self):
        r = self._chat()
        conv = frappe.get_doc(CONV, r["conversation"])
        link = feedback.feedback_link(conv)
        token = link.split("t=")[1]
        from thinknxg_support.api.v1 import feedback as api

        as_user("Guest")
        with self.assertRaises(frappe.PermissionError):
            api.form(conv.name, "wrong")
        self.assertFalse(api.form(conv.name, token)["done"])
        api.submit(conv.name, token, 4, "Yes")
        self.assertTrue(api.form(conv.name, token)["done"])

    def test_agents_see_only_their_feedback(self):
        r = self._chat()
        feedback.submit(frappe.get_doc(CONV, r["conversation"]), 3, "Partially")
        as_user(self.other)
        self.assertEqual(frappe.get_list(FB, pluck="name"), [])
        as_user(self.agent)
        self.assertEqual(len(frappe.get_list(FB, pluck="name")), 1)
        as_user(self.manager)
        self.assertEqual(len(frappe.get_list(FB, pluck="name")), 1)

    def test_report(self):
        r = self._chat()
        feedback.submit(frappe.get_doc(CONV, r["conversation"]), 5, "Yes")
        from thinknxg_support.thinknxg_support.report.agent_csat.agent_csat import execute

        today = frappe.utils.today()
        cols, data, _m, _c = execute({"from_date": today, "to_date": today, "period": "Agent"})
        row = next(d for d in data if d["agent"] == self.agent)
        self.assertEqual((row["surveys"], row["avg_rating"], row["csat"]), (1, 5.0, 100.0))

    def test_survey_off(self):
        frappe.db.set_single_value("Support Portal Settings", "survey_mode", "Off")
        from thinknxg_support.utils import clear_request_cache

        clear_request_cache()
        r = self._chat()
        self.assertIsNone(feedback.survey_config())
        with self.assertRaises(frappe.ValidationError):
            feedback.submit(frappe.get_doc(CONV, r["conversation"]), 5, "Yes")

    def test_administrator_counts_as_agent(self):
        self.assertTrue(alerts.is_agent("Administrator"))
