"""1.10 copilot and message analysis, with the AI provider mocked (no network)."""
import json
from unittest.mock import patch

import frappe

from thinknxg_support.integrations import live_chat
from thinknxg_support.integrations.ai import common, copilot, engine, providers
from thinknxg_support.tests.utils import BaseTestCase, as_user

CONV = "Support Conversation Link"
MSG = "Support Portal Message"


def run_now(fn, **kw):
    fn = frappe.get_attr(fn) if isinstance(fn, str) else fn
    return fn(**{k: v for k, v in kw.items() if k not in ("queue", "enqueue_after_commit", "job_id", "deduplicate",
                                                          "timeout", "now", "at_front", "job_name", "is_async")})


class FakeProvider:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def __call__(self, system, messages, on_delta=None, max_tokens=None, temperature=None):
        self.calls.append({"system": system, "user": messages[-1]["content"]})
        text = self.replies.pop(0) if self.replies else ""
        return {"text": text, "provider": "Fake", "model": "fake", "prompt_tokens": 10, "completion_tokens": 5}


class TestCopilot(BaseTestCase):
    def setUp(self):
        as_user("Administrator")
        self._ai(enable_ai=0)
        s = frappe.get_single("Support AI Settings")
        s.update({"enable_ai": 0, "enable_copilot": 1, "analyze_messages": 1, "summary_on_handoff": 1, "alert_on_negative": 1,
                  "provider": "OpenAI Compatible", "api_base_url": "https://ai.example.com/v1", "model": "fake",
                  "daily_token_budget": 0, "tone": "Empathetic", "persona": "A patient guide", "history_turns": 4})
        s.flags.ignore_permissions = True
        s.flags.ignore_validate = True
        s.save()
        frappe.db.set_single_value("Support Portal Settings", {"enable_live_chat": 1, "allow_guest_chat": 1,
                                                              "guest_chat_rate_limit": 1000})
        frappe.cache.delete_keys("thinknxg_support:rl:")
        self.enq = patch.object(frappe, "enqueue", side_effect=run_now)
        self.enq.start()

    def tearDown(self):
        self.enq.stop()
        self._ai(analyze_messages=0, enable_ai=0)
        as_user("Administrator")

    def _ai(self, **values):
        frappe.db.set_single_value("Support AI Settings", values)
        frappe.clear_document_cache("Support AI Settings", "Support AI Settings")

    def _chat(self, text="My order SO-1001 is late, this is the third time!"):
        as_user("Guest")
        r = live_chat.start_guest(text, name="Rana Khalid", email="rana@example.com")
        as_user("Administrator")
        frappe.db.set_value(CONV, r["conversation"], "handling", "Agent", update_modified=False)
        return frappe.get_doc(CONV, r["conversation"])

    def test_tone_persona_and_memory_reach_the_assistant(self):
        c = engine.cfg()
        self.assertIn("empathetic", engine.style_instructions(c))
        self.assertIn("A patient guide", engine._system(c))
        self.assertEqual(engine.history_turns(c), 4)

    def test_analysis_stores_insight_and_alerts_on_frustration(self):
        self._ai(enable_ai=1)
        fake = FakeProvider([json.dumps({"intent": "late delivery complaint", "sentiment": "negative", "frustrated": True,
                                         "urgency": "high", "language": "en",
                                         "entities": {"order_ids": ["SO-1001"]}})] * 3)
        from thinknxg_support.integrations import alerts, escalations

        with patch.object(providers, "complete", side_effect=fake), patch.object(alerts, "raise_alert") as raised, \
                patch.object(escalations, "on_negative_sentiment") as esc, \
                patch("thinknxg_support.integrations.ai.engine.respond"):
            conv = self._chat()
        msg = frappe.get_all(MSG, filters={"conversation": conv.name, "direction": "Inbound"}, fields=["*"], limit=1)[0]
        self.assertEqual((msg.ai_sentiment, msg.ai_urgency, int(msg.ai_frustrated)), ("Negative", "High", 1))
        self.assertEqual(json.loads(msg.ai_entities)["order_ids"], ["SO-1001"])
        conv.reload()
        self.assertEqual((conv.sentiment, conv.urgency, conv.customer_language), ("Negative", "High", "en"))
        self.assertTrue(any(c.args[0] == "Frustrated Customer" for c in raised.call_args_list))
        esc.assert_called_once()
        self.assertNotIn("rana@example.com", "".join(c["user"] for c in fake.calls))  # contact details redacted

    def test_analysis_is_off_unless_switched_on(self):
        self._ai(analyze_messages=0)
        fake = FakeProvider([])
        with patch.object(providers, "complete", side_effect=fake):
            self._chat("hello")
        self.assertEqual(fake.calls, [])

    def test_copilot_drafts_rewrite_translate_summary_and_note(self):
        self._ai(analyze_messages=0)
        conv = self._chat()
        fake = FakeProvider([
            json.dumps([{"label": "Apologise", "text": "I'm sorry about the delay."}, {"label": "Ask", "text": "Which address?"}]),
            "Thank you for your patience.",
            "شكرا لصبرك",
            "- Late order SO-1001\n- Next: check courier",
            json.dumps({"solution": "Check the courier tracking.", "follow_ups": ["Is the address correct?"], "sources": []}),
            "- Late order\n- Next: courier",
        ])
        with patch.object(providers, "complete", side_effect=fake):
            s = copilot.suggest_replies(conv)
            self.assertEqual([x["label"] for x in s["suggestions"]], ["Apologise", "Ask"])
            self.assertEqual(copilot.rewrite("thx for waiting", "professional", conv)["text"], "Thank you for your patience.")
            self.assertEqual(copilot.translate("Thanks for your patience", "ar", conv)["text"], "شكرا لصبرك")
            self.assertIn("SO-1001", copilot.summarize(conv)["summary"])
            self.assertEqual(copilot.recommend(conv)["follow_ups"], ["Is the address correct?"])
            n = copilot.auto_note(conv)
        conv.reload()
        self.assertTrue(conv.summary)
        note = frappe.get_doc(MSG, n["message"])
        self.assertTrue(note.is_internal)  # drafts and notes never reach the customer
        kinds = frappe.get_all("Support AI Usage Log", filters={"conversation": conv.name}, pluck="kind")
        self.assertTrue({"Copilot", "Translation", "Summary"} <= set(kinds))

    def test_copilot_respects_switch_and_budget(self):
        conv = self._chat("hi")
        self._ai(enable_copilot=0)
        with self.assertRaises(common.Unavailable):
            copilot.suggest_replies(conv)
        self._ai(enable_copilot=1)
        with patch.object(providers, "budget_left", return_value=False), self.assertRaises(common.Unavailable):
            copilot.rewrite("hello", "friendly", conv)

    def test_handoff_adds_a_summary_note(self):
        self._ai(analyze_messages=0, enable_ai=1)
        conv = self._chat("I want to speak to a person about my refund")
        frappe.db.set_value(CONV, conv.name, "handling", "Bot", update_modified=False)
        conv.reload()
        fake = FakeProvider(["- Wants a refund\n- Next: check order"])
        from thinknxg_support.integrations import routing

        with patch.object(providers, "complete", side_effect=fake):
            routing.handoff(conv, "Customer asked for a person")
        notes = frappe.get_all(MSG, filters={"conversation": conv.name, "is_internal": 1, "response_source": "AI summary"})
        self.assertEqual(len(notes), 1)

    def test_web_console_and_staff_api_need_staff(self):
        conv = self._chat("hi")
        cust = "copilot-customer@example.com"
        if not frappe.db.exists("User", cust):
            frappe.get_doc({"doctype": "User", "email": cust, "first_name": "Cust", "user_type": "Website User",
                            "send_welcome_email": 0}).insert(ignore_permissions=True)
        as_user(cust)
        from thinknxg_support.api.staff import v1
        from thinknxg_support.api.v1 import copilot as console

        self.assertRaises(frappe.PermissionError, console.summarize, conv.name)
        self.assertRaises(frappe.PermissionError, v1.copilot, conv.name, "summarize")
