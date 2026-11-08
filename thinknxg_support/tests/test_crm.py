"""1.14 increment 3: leads from chats, lead capture, lead score and automation rules."""
import json
import unittest
from unittest.mock import patch

import frappe
from frappe.utils import add_to_date, now_datetime

from thinknxg_support.api.staff import v1
from thinknxg_support.integrations import automation, crm, lead_capture, lead_score, live_chat
from thinknxg_support.integrations.ai import providers
from thinknxg_support.tests.utils import BaseTestCase, as_user

CONV = "Support Conversation Link"
MSG = "Support Portal Message"
RULE = "Support Automation Rule"
ENQ = ("queue", "enqueue_after_commit", "job_id", "deduplicate", "timeout", "now", "at_front", "job_name", "is_async")


def run_now(fn, **kw):
    fn = frappe.get_attr(fn) if isinstance(fn, str) else fn
    return fn(**{k: v for k, v in kw.items() if k not in ENQ})


def make_user(email, roles):
    if not frappe.db.exists("User", email):
        frappe.get_doc({"doctype": "User", "email": email, "first_name": email.split("@")[0], "send_welcome_email": 0,
                        "roles": [{"role": r} for r in roles]}).insert(ignore_permissions=True)
    return email


class Base(BaseTestCase):
    target = "ERPNext Lead"

    def setUp(self):
        as_user("Administrator")
        frappe.db.set_single_value("Support Portal Settings", {
            "enable_live_chat": 1, "allow_guest_chat": 1, "guest_chat_rate_limit": 1000, "lead_target": self.target,
            "lead_source": "Live Chat"})
        frappe.db.set_single_value("Support AI Settings", {"enable_ai": 0, "analyze_messages": 0, "enable_lead_scoring": 0,
                                                           "localize_messages": 0, "translate_questions": 0})
        for dt in ("Support Portal Settings", "Support AI Settings"):
            frappe.clear_document_cache(dt, dt)
        frappe.cache.delete_keys("thinknxg_support:rl:")
        from thinknxg_support.utils import clear_request_cache

        clear_request_cache()
        frappe.db.delete(RULE)
        self.agent = make_user("crm-agent@example.com", ["Support Agent"])
        self.enq = patch.object(frappe, "enqueue", side_effect=run_now)
        self.enq.start()

    def tearDown(self):
        self.enq.stop()
        as_user("Administrator")

    def chat(self, text="Hello, I want a quote for 20 licences", email="maya@acme.example", name="Maya Haddad", **values):
        as_user("Guest")
        with patch("thinknxg_support.integrations.ai.engine.respond"):
            r = live_chat.start_guest(text, name=name, email=email)
        as_user("Administrator")
        frappe.db.set_value(CONV, r["conversation"], {"assigned_agent": self.agent, **values}, update_modified=False)
        return frappe.get_doc(CONV, r["conversation"]), r["token"]

    def lead_doctype(self):
        return crm.target()


class TestLeads(Base):
    def test_agent_creates_a_lead_from_the_chat_and_it_appears_on_the_timeline(self):
        conv, _t = self.chat(email="maya.lead@acme.example")
        as_user(self.agent)
        out = v1.create_lead(conv.name, company="Acme Trading")
        lead = out["lead"]
        dt = self.lead_doctype()
        self.assertEqual(lead["doctype"], dt)
        doc = frappe.get_doc(dt, lead["name"])
        self.assertEqual(doc.get("email_id") or doc.get("email"), "maya.lead@acme.example")
        self.assertEqual(doc.get("company_name") or doc.get("organization"), "Acme Trading")
        self.assertTrue(frappe.db.exists("Comment", {"reference_doctype": dt, "reference_name": lead["name"],
                                                     "content": ["like", f"%{conv.name}%"]}))
        # a second chat from the same person links the same lead
        conv2, _t = self.chat(email="maya.lead@acme.example")
        as_user(self.agent)
        self.assertEqual(v1.create_lead(conv2.name)["lead"]["name"], lead["name"])

    def test_chat_end_goes_on_the_timeline(self):
        conv, _t = self.chat(email="maya.end@acme.example")
        out = crm.create_lead(conv)
        frappe.db.set_value(CONV, conv.name, {"needs_follow_up": "No", "closure_reason": "Resolved"}, update_modified=False)
        live_chat._close(frappe.get_doc(CONV, conv.name))
        comments = frappe.get_all("Comment", filters={"reference_doctype": out["doctype"], "reference_name": out["name"]},
                                  pluck="content")
        self.assertTrue(any("Chat ended" in c for c in comments))

    def test_lead_needs_contact_details_and_agent_access(self):
        conv, _t = self.chat()
        frappe.db.set_value(CONV, conv.name, {"guest_email": None, "guest_phone": None}, update_modified=False)
        as_user(self.agent)
        self.assertRaises(frappe.ValidationError, v1.create_lead, conv.name)
        self.assertRaises(frappe.ValidationError, v1.create_lead, conv.name, email="not-an-email")
        outsider = make_user("crm-out@example.com", ["Support Agent"])
        q = frappe.get_all("Support Chat Queue", pluck="name", limit=1)
        frappe.db.set_value(CONV, conv.name, {"assigned_agent": None, "queue": q[0] if q else None}, update_modified=False)
        if q:
            as_user(outsider)
            self.assertRaises(frappe.PermissionError, v1.create_lead, conv.name, email="x@y.example")

    def test_leads_can_be_switched_off(self):
        frappe.db.set_single_value("Support Portal Settings", "lead_target", "Off")
        frappe.clear_document_cache("Support Portal Settings", "Support Portal Settings")
        from thinknxg_support.utils import clear_request_cache

        clear_request_cache()
        conv, _t = self.chat()
        self.assertRaises(frappe.ValidationError, crm.create_lead, conv)
        self.assertFalse(v1.bootstrap()["capabilities"]["leads"])


class TestLeadCapture(Base):
    def say(self, conv, token, text):
        as_user("Guest")
        with patch("thinknxg_support.integrations.ai.engine.respond") as respond:
            live_chat.guest_send(conv.name, token, text)
        as_user("Administrator")
        return respond

    def bot_said(self, conv):
        rows = frappe.get_all(MSG, filters={"conversation": conv.name, "sender_type": "Bot"}, pluck="content",
                              order_by="creation desc", limit=1)
        return frappe.utils.strip_html(rows[0]) if rows else ""

    def test_details_are_collected_one_question_at_a_time(self):
        conv, token = self.chat()
        frappe.db.set_value(CONV, conv.name, {"guest_email": None, "guest_name": None, "assigned_agent": None,
                                              "handling": "Bot"}, update_modified=False)
        conv.reload()
        self.assertTrue(lead_capture.start(conv, intro="Let me take your details."))
        self.assertIn("name", self.bot_said(conv))
        respond = self.say(conv, token, "Omar Said")
        self.assertFalse(respond.called, "the assistant does not answer while details are collected")
        self.assertIn("e-mail", self.bot_said(conv))
        self.say(conv, token, "not an email")
        self.assertIn("does not look like", self.bot_said(conv))
        self.say(conv, token, "my mail is omar@said.example")
        self.say(conv, token, "skip")  # phone
        self.say(conv, token, "Said Logistics")
        conv.reload()
        self.assertFalse(lead_capture.active(conv))
        self.assertEqual(conv.guest_email, "omar@said.example")
        lead = frappe.get_doc(conv.lead_doctype, conv.lead)
        self.assertEqual(lead.get("company_name") or lead.get("organization"), "Said Logistics")
        self.assertIn("Thank you", self.bot_said(conv))

    def test_cancel_stops_and_agents_are_not_interrupted(self):
        conv, token = self.chat()
        frappe.db.set_value(CONV, conv.name, {"guest_email": None, "guest_name": None, "handling": "Bot"},
                            update_modified=False)
        conv.reload()
        lead_capture.start(conv)
        self.say(conv, token, "cancel")
        self.assertFalse(lead_capture.active(frappe.get_doc(CONV, conv.name)))
        lead_capture.start(frappe.get_doc(CONV, conv.name))
        frappe.db.set_value(CONV, conv.name, "handling", "Agent", update_modified=False)
        self.assertFalse(lead_capture.consume(frappe.get_doc(CONV, conv.name), "Omar"))

    def test_chatbot_rule_can_collect_details(self):
        from thinknxg_support.integrations.ai import engine

        conv, token = self.chat()
        frappe.db.set_value(CONV, conv.name, {"guest_email": None, "guest_name": None, "handling": "Bot"},
                            update_modified=False)
        rule = frappe._dict(rule_name="Sales", action="Collect Details", response="I can help with a quote.", buttons=None)
        engine.run_rule(frappe.get_doc(CONV, conv.name), None, rule, "quote")
        self.assertTrue(lead_capture.active(frappe.get_doc(CONV, conv.name)))


class TestLeadScore(Base):
    def test_score_is_stored_with_reasons_when_switched_on(self):
        conv, _t = self.chat()
        self.assertIsNone(lead_score.score(conv.name))  # off by default
        frappe.db.set_single_value("Support AI Settings", {"enable_lead_scoring": 1, "model": "fake", "daily_token_budget": 0})
        frappe.clear_document_cache("Support AI Settings", "Support AI Settings")
        fake = {"text": json.dumps({"score": 82, "reasons": ["Asks for a quote", "20 licences"]}), "provider": "Fake",
                "model": "fake", "prompt_tokens": 10, "completion_tokens": 10}
        with patch.object(providers, "complete", return_value=fake):
            out = lead_score.score(conv.name)
        self.assertEqual(out["score"], 82)
        self.assertEqual(frappe.db.get_value(CONV, conv.name, "lead_score"), 82)
        self.assertTrue(frappe.db.exists("Support AI Usage Log", {"conversation": conv.name, "kind": "Lead Score"}))


class TestAutomation(Base):
    def rule(self, **kw):
        return frappe.get_doc({"doctype": RULE, "channel_live_chat": 1, **kw}).insert()

    def test_rules_reject_actions_that_do_not_fit(self):
        self.assertRaises(frappe.ValidationError, self.rule, rule_name="bad", trigger="Visitor on a Page",
                          action="Close Chat", message="x")
        self.assertRaises(frappe.ValidationError, self.rule, rule_name="bad2", trigger="Customer Quiet",
                          action="Send Message")  # no message

    def test_page_messages_reach_the_widget_config(self):
        self.rule(rule_name="Pricing help", trigger="Visitor on a Page", action="Send Message", page_pattern="/pricing*",
                  seconds_on_page=15, message="Questions about plans?")
        cfg = live_chat.widget_config()
        self.assertEqual(cfg["proactive"], [{"rule": "Pricing help", "pattern": "/pricing*", "seconds": 15,
                                             "message": "Questions about plans?"}])
        self.assertTrue(automation.page_matches("/pricing*", "/pricing/teams"))
        self.assertFalse(automation.page_matches("/pricing*", "/blog"))

    def test_quiet_customer_gets_one_nudge_per_quiet_spell(self):
        self.rule(rule_name="Nudge", trigger="Customer Quiet", action="Send Message", quiet_minutes=10,
                  message="Are you still there?")
        conv, token = self.chat()
        from thinknxg_support.integrations import conversations

        as_user(self.agent)
        out = conversations.post_agent_message(conv, "<p>Which plan?</p>")
        as_user("Administrator")
        old = add_to_date(now_datetime(), minutes=-15)
        for m in frappe.get_all(MSG, filters={"conversation": conv.name, "direction": "Inbound"}, pluck="name"):
            frappe.db.set_value(MSG, m, "creation", add_to_date(old, minutes=-5), update_modified=False)
        frappe.db.set_value(MSG, out["name"], "creation", old, update_modified=False)
        frappe.db.set_value(CONV, conv.name, "last_activity_at", old, update_modified=False)
        automation.check_quiet()
        automation.check_quiet()
        nudges = frappe.get_all(MSG, filters={"conversation": conv.name, "response_source": "Automation: Nudge"})
        self.assertEqual(len(nudges), 1)
        self.assertEqual(frappe.db.get_value(RULE, "Nudge", "runs"), 1)

    def test_follow_up_task_when_a_chat_ends_needing_follow_up(self):
        self.rule(rule_name="Follow up", trigger="Chat Closed Needing Follow-up", action="Create Follow-up Task",
                  task_days=2)
        conv, _t = self.chat()
        frappe.db.set_value(CONV, conv.name, {"needs_follow_up": "Yes", "closed_by": self.agent}, update_modified=False)
        live_chat._close(frappe.get_doc(CONV, conv.name))
        self.assertTrue(frappe.db.exists("ToDo", {"reference_type": CONV, "reference_name": conv.name,
                                                  "allocated_to": self.agent, "status": "Open"}))

    def test_outside_hours_collects_details_instead_of_the_offline_message(self):
        self.rule(rule_name="After hours", trigger="New Chat Outside Chat Hours", action="Collect Details",
                  message="We are closed now. Leave your details and we will call you.")
        conv, _t = self.chat()
        frappe.db.set_value(CONV, conv.name, {"guest_email": None, "guest_name": None, "handling": "Bot",
                                              "assigned_agent": None}, update_modified=False)
        from thinknxg_support.integrations import routing

        with patch.object(live_chat, "is_online", return_value=False):
            routing.handoff(frappe.get_doc(CONV, conv.name), "Customer asked for a person")
        texts = [frappe.utils.strip_html(c) for c in frappe.get_all(MSG, filters={"conversation": conv.name,
                                                                                    "direction": "Outbound"}, pluck="content")]
        self.assertTrue(any("We are closed now" in t for t in texts))
        self.assertTrue(lead_capture.active(frappe.get_doc(CONV, conv.name)))

    def test_escalate_action_uses_escalations(self):
        frappe.db.set_single_value("Support Escalation Settings", "enabled", 1)
        frappe.clear_document_cache("Support Escalation Settings", "Support Escalation Settings")
        rule = self.rule(rule_name="Escalate quiet", trigger="Customer Quiet", action="Notify or Escalate",
                         quiet_minutes=5, escalation_priority="High")
        conv, _t = self.chat()
        result = automation.run(rule, conv, "quiet")
        self.assertIn("escalation", result)
        self.assertTrue(frappe.db.exists("Support Escalation", {"reference_name": conv.name,
                                                                 "escalation_type": "Automation Rule"}))


class TestAnalytics(Base):
    def test_leads_and_automation_runs_are_counted(self):
        from thinknxg_support.integrations import analytics

        conv, _t = self.chat(email="count.me@acme.example")
        crm.create_lead(conv)
        analytics.refresh()
        t = analytics.overview()["totals"]
        self.assertGreaterEqual(t["leads"], 1)
        self.assertIn("lead_conversions", t)


class TestThinkNXGCRM(TestLeads):
    """The same lead tests against thinkNXG CRM's CRM Lead (run where the CRM app is installed)."""
    target = "thinkNXG CRM (CRM Lead)"

    def setUp(self):
        if not frappe.db.exists("DocType", "CRM Lead"):
            raise unittest.SkipTest("thinkNXG CRM is not installed on this site")
        super().setUp()
