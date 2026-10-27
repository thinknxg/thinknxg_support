"""AI assistant, chatbot rules and handoff. The model provider is mocked: no network calls."""
from unittest.mock import patch

import frappe

from thinknxg_support.integrations import live_chat
from thinknxg_support.integrations.ai import providers, retrieval
from thinknxg_support.tests.utils import BaseTestCase, as_user
from thinknxg_support.utils import clear_request_cache

CONV = "Support Conversation Link"
MSG = "Support Portal Message"


def run_now(fn, **kw):
    fn = frappe.get_attr(fn) if isinstance(fn, str) else fn
    args = {k: v for k, v in kw.items() if k not in ("queue", "enqueue_after_commit", "job_id", "deduplicate", "timeout")}
    return fn(**args)


def reply(text, meta):
    import json

    return {"text": text + "\n###META###" + json.dumps(meta), "prompt_tokens": 100, "completion_tokens": 20,
            "latency_ms": 900, "first_token_ms": 300, "model": "test-model", "provider": "OpenAI Compatible"}


class TestAssistant(BaseTestCase):
    def setUp(self):
        as_user("Administrator")
        frappe.db.set_single_value("Support Portal Settings", {"enable_live_chat": 1, "allow_guest_chat": 1,
                                                              "enable_raven": 0, "guest_chat_rate_limit": 1000,
                                                              "chat_days": "Mon,Tue,Wed,Thu,Fri,Sat,Sun",
                                                              "chat_start_time": "00:00:00", "chat_end_time": "23:59:59"})
        s = frappe.get_single("Support AI Settings")
        s.update({"enable_ai": 1, "model": "test-model", "api_base_url": "http://localhost:9/v1", "answer_guests": 1,
                  "channel_live_chat": 1, "only_answer_from_kb": 1, "use_embeddings": 0, "min_relevance": 0.3,
                  "handoff_on": "Low", "max_ai_replies": 15, "daily_token_budget": 0, "index_snippets": 1,
                  "index_helpdesk_articles": 0})
        s.flags.ignore_permissions = True
        s.save()
        frappe.db.set_value("Support Chatbot", {"enabled": 1}, "enabled", 0)
        for q, audience in (("How do I reset my password?", "Everyone"), ("What is our contract discount?", "Customers")):
            if not frappe.db.exists("Support Knowledge Snippet", {"question": q}):
                frappe.get_doc({"doctype": "Support Knowledge Snippet", "question": q, "audience": audience,
                                "answer": f"<p>Answer for: {q} Open Settings and choose Reset password.</p>"}).insert()
        retrieval.rebuild()
        clear_request_cache()
        frappe.cache.delete_keys("thinknxg_support:rl:")
        as_user("Guest")

    def tearDown(self):
        as_user("Administrator")

    def _chat(self, text):
        with patch.object(frappe, "enqueue", side_effect=run_now):
            r = live_chat.start_guest(f"<p>{text}</p>", name="Test Visitor", email="visitor@example.com")
        return r, frappe.get_doc(CONV, r["conversation"])

    def test_retrieval_respects_audience(self):
        guest = retrieval.search("contract discount", "Everyone")
        self.assertFalse(any("contract" in p["title"].lower() for p in guest))
        cust = retrieval.search("contract discount", "Customers")
        self.assertTrue(any("contract" in p["title"].lower() for p in cust))

    def test_confident_answer_stays_with_assistant(self):
        with patch.object(providers, "complete", return_value=reply("Open **Settings** and choose Reset.",
                                                                    {"confidence": "high", "handoff": False, "sources": ["S1"],
                                                                     "follow_ups": ["How long does it take?"]})):
            r, conv = self._chat("How do I reset my password?")
        conv.reload()
        self.assertEqual(conv.handling, "Bot")
        self.assertEqual(conv.ai_replies, 1)
        msgs = live_chat.guest_messages(r["conversation"], r["token"])["messages"]
        ai = [m for m in msgs if m["sender_type"] == "AI"]
        self.assertEqual(len(ai), 1)
        self.assertIn("<b>Settings</b>", ai[0]["content"])
        self.assertTrue(ai[0]["sources"])
        self.assertEqual(ai[0]["follow_ups"], ["How long does it take?"])
        self.assertTrue(frappe.db.exists("Support AI Usage Log", {"conversation": conv.name, "status": "Success"}))

    def test_low_confidence_hands_off(self):
        with patch.object(providers, "complete", return_value=reply("Not sure.", {"confidence": "low", "handoff": True})):
            r, conv = self._chat("How do I reset my password on the old system?")
        conv.reload()
        self.assertEqual(conv.handling, "Queued")
        self.assertTrue(conv.handoff_at)
        types = [m["sender_type"] for m in live_chat.guest_messages(r["conversation"], r["token"])["messages"]]
        self.assertIn("System", types)

    def test_no_passages_hands_off_without_calling_model(self):
        with patch.object(providers, "complete") as call:
            r, conv = self._chat("Can you fix my printer driver xyzzy?")
        call.assert_not_called()
        conv.reload()
        self.assertEqual(conv.handling, "Queued")

    def test_provider_error_hands_off_and_logs(self):
        with patch.object(providers, "complete", side_effect=providers.AIError("HTTP 500: boom")):
            r, conv = self._chat("How do I reset my password?")
        conv.reload()
        self.assertEqual(conv.handling, "Queued")
        self.assertTrue(frappe.db.exists("Support AI Usage Log", {"conversation": conv.name, "status": "Error"}))

    def test_customer_asks_for_person(self):
        as_user("Administrator")
        frappe.get_doc({"doctype": "Support Chatbot", "bot_name": "_Test Bot", "enabled": 1, "channel_live_chat": 1,
                        "handoff_keywords": "agent, human", "fallback_action": "Hand Off",
                        "rules": [{"rule_name": "hours", "trigger_type": "Keywords", "trigger": "opening hours",
                                   "response": "Sunday to Thursday.", "buttons": "Talk to a person | @agent"}]}).insert()
        as_user("Guest")
        try:
            with patch.object(providers, "complete") as call:
                r, conv = self._chat("What are your opening hours?")
                msgs = live_chat.guest_messages(r["conversation"], r["token"])["messages"]
                bot = [m for m in msgs if m["sender_type"] == "Bot"]
                self.assertEqual(bot[0]["buttons"], [{"label": "Talk to a person", "payload": "@agent"}])
                with patch.object(frappe, "enqueue", side_effect=run_now):
                    live_chat.guest_send(r["conversation"], r["token"], "Talk to a person", payload="@agent")
            call.assert_not_called()
            conv.reload()
            self.assertEqual(conv.handling, "Queued")
        finally:
            as_user("Administrator")
            frappe.delete_doc("Support Chatbot", "_Test Bot", force=True)

    def test_agent_reply_takes_over(self):
        with patch.object(providers, "complete", return_value=reply("Not sure.", {"confidence": "low", "handoff": True})):
            r, conv = self._chat("How do I reset my password?")
        as_user("Administrator")
        from thinknxg_support.integrations.conversations import post_agent_message

        conv.reload()
        post_agent_message(conv, "<p>Hi, I can help.</p>")
        conv.reload()
        self.assertEqual(conv.handling, "Agent")
        self.assertTrue(conv.first_agent_reply_at)
        self.assertEqual(conv.assigned_agent, "Administrator")

    def test_feedback_only_on_ai_messages(self):
        with patch.object(providers, "complete", return_value=reply("Open Settings.", {"confidence": "high", "sources": ["S1"]})):
            r, conv = self._chat("How do I reset my password?")
        msgs = live_chat.guest_messages(r["conversation"], r["token"])["messages"]
        ai = next(m for m in msgs if m["sender_type"] == "AI")
        mine = next(m for m in msgs if m["from_customer"])
        conv.reload()
        live_chat.feedback(conv, ai["id"], "Helpful")
        self.assertEqual(frappe.db.get_value(MSG, ai["id"], "feedback"), "Helpful")
        with self.assertRaises(frappe.PermissionError):
            live_chat.feedback(conv, mine["id"], "Helpful")

    def test_reply_limit(self):
        as_user("Administrator")
        frappe.db.set_single_value("Support AI Settings", "max_ai_replies", 1)
        clear_request_cache()
        as_user("Guest")
        with patch.object(providers, "complete", return_value=reply("Open Settings.", {"confidence": "high", "sources": ["S1"]})) as call:
            r, conv = self._chat("How do I reset my password?")
            with patch.object(frappe, "enqueue", side_effect=run_now):
                live_chat.guest_send(r["conversation"], r["token"], "And how do I reset my password again?")
        self.assertEqual(call.call_count, 1)
        conv.reload()
        self.assertEqual(conv.handling, "Queued")
