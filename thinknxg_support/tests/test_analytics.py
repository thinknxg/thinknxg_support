"""1.13: analytics figures against a known set of chats, permissions per role, privacy export and erase, usage
limits, and the security check."""
import json
from unittest.mock import patch

import frappe
from frappe.utils import add_to_date, now_datetime

from thinknxg_support.api.v1 import analytics as api
from thinknxg_support.integrations import analytics, limits, live_chat, privacy, security
from thinknxg_support.integrations.ai import providers
from thinknxg_support.tests.utils import BaseTestCase, as_user

CONV = "Support Conversation Link"
MSG = "Support Portal Message"
REQ = "Support Privacy Request"


def make_user(email, roles):
    if not frappe.db.exists("User", email):
        frappe.get_doc({"doctype": "User", "email": email, "first_name": email.split("@")[0], "send_welcome_email": 0,
                        "roles": [{"role": r} for r in roles]}).insert(ignore_permissions=True)
    return email


class Base(BaseTestCase):
    def setUp(self):
        as_user("Administrator")
        frappe.db.set_single_value("Support Portal Settings", {"enable_live_chat": 1, "allow_guest_chat": 1,
                                                              "guest_chat_rate_limit": 1000})
        frappe.db.set_single_value("Support AI Settings", {"enable_ai": 0, "analyze_messages": 0, "summary_on_handoff": 0,
                                                           "daily_token_budget": 0})
        frappe.clear_document_cache("Support AI Settings", "Support AI Settings")
        frappe.cache.delete_keys("thinknxg_support:rl:")
        analytics.refresh()
        self.manager = make_user("sa-manager@example.com", ["Support Manager"])
        self.agent = make_user("sa-agent@example.com", ["Support Agent"])

    def tearDown(self):
        as_user("Administrator")

    def chat(self, text="Hello, where is my order?", email="nadia@example.com", phone=None, **values):
        as_user("Guest")
        with patch("thinknxg_support.integrations.ai.engine.respond"):
            r = live_chat.start_guest(text, name="Nadia Saleh", email=email, phone=phone)
        as_user("Administrator")
        if values:
            frappe.db.set_value(CONV, r["conversation"], values, update_modified=False)
        return r["conversation"]


class TestAnalytics(Base):
    def _queue(self):
        if not frappe.db.exists("Support Chat Queue", "SA Test Queue"):
            frappe.get_doc({"doctype": "Support Chat Queue", "queue_name": "SA Test Queue", "assignment_rule": "Manual"}).insert()
        frappe.db.delete(CONV, {"queue": "SA Test Queue"})
        frappe.db.delete("Support Chat Assignment", {"queue": "SA Test Queue"})
        return "SA Test Queue"

    def test_figures_match_a_known_set_of_chats(self):
        q = self._queue()
        t0 = add_to_date(now_datetime(), hours=-3)
        self.chat(queue=q, creation=t0, ai_replies=2, status="Closed", closed_on=add_to_date(t0, minutes=5),
                  resolved_by_assistant=1, handling="Bot", intent="Delivery time", sentiment="Neutral")
        human = self.chat(queue=q, creation=t0, ai_replies=1, handoff_at=add_to_date(t0, minutes=1),
                          first_agent_reply_at=add_to_date(t0, minutes=3), status="Closed",
                          closed_on=add_to_date(t0, minutes=21), handling="Agent", assigned_agent=self.agent,
                          handoff_reason="Customer asked for a person", sentiment="Negative", customer_language="ar")
        waiting = self.chat(queue=q, creation=add_to_date(now_datetime(), minutes=-10), handling="Queued",
                            handoff_at=add_to_date(now_datetime(), minutes=-4))
        frappe.get_doc({"doctype": "Support Chat Assignment", "conversation": human, "agent": self.agent, "queue": q,
                        "reason": "Automatic", "assigned_at": add_to_date(t0, minutes=1),
                        "first_response_at": add_to_date(t0, minutes=3), "ended_at": add_to_date(t0, minutes=21),
                        "outcome": "Resolved"}).insert(ignore_permissions=True)
        analytics.refresh()
        o = analytics.overview(queue=q)
        t = o["totals"]
        self.assertEqual((t["conversations"], t["ai_resolved"], t["human_handled"], t["other"]), (3, 1, 1, 1))
        self.assertEqual((t["ai_answered"], t["ai_resolution_rate"], t["automation_rate"]), (2, 50.0, 33.3))
        self.assertEqual((t["handoffs"], t["closed"]), (2, 2))
        self.assertEqual(t["first_response_median"], 120)  # handoff to first reply
        self.assertEqual(t["resolution_median"], 780)  # 5 and 21 minutes
        self.assertEqual(sum(d["ai"] + d["human"] + d["other"] for d in o["daily"]), 3)
        self.assertIn("Customer asked for a person", [r["label"] for r in o["handoff_reasons"]])
        self.assertIn("delivery time", [r["label"] for r in o["intents"]])
        self.assertIn("ar", [r["label"] for r in o["languages"]])
        row = next(a for a in analytics.agents(queue=q) if a["agent"] == self.agent)
        self.assertEqual((row["chats"], row["first_response_median"], row["handling_median"]), (1, 120, 1200))
        self.assertEqual(analytics._pct([10, 20, 30, 40, 50, 60, 70, 80, 90, 100], 0.9), 91.0)
        live = analytics.live()
        self.assertGreaterEqual(live["waiting_count"], 1)
        self.assertGreaterEqual(live["longest_wait_seconds"], 240)
        self.assertEqual([e["at"] for e in live["events"]], sorted((e["at"] for e in live["events"]), reverse=True))
        self.assertTrue(frappe.db.exists(CONV, {"name": waiting, "handling": "Queued"}))

    def test_only_managers_see_analytics(self):
        for user, allowed in ((self.manager, True), (self.agent, False), ("Guest", False)):
            as_user(user)
            for fn in (api.overview, api.agents, api.live, api.usage, api.security_checks):
                if allowed:
                    fn()
                else:
                    self.assertRaises(frappe.PermissionError, fn)
        as_user(self.manager)
        self.assertRaises(frappe.PermissionError, api.require_two_factor)  # System Managers only

    def test_results_are_cached_until_refreshed(self):
        analytics.refresh()
        first = analytics.overview()
        self.chat()
        self.assertEqual(analytics.overview()["totals"]["conversations"], first["totals"]["conversations"])
        analytics.refresh()
        self.assertEqual(analytics.overview()["totals"]["conversations"], first["totals"]["conversations"] + 1)


class TestPrivacy(Base):
    def _request(self, kind, **kw):
        return frappe.get_doc({"doctype": REQ, "request_type": kind, "identity_verified": 1, **kw}).insert()

    def test_export_contains_the_persons_chats_without_staff_notes(self):
        name = self.chat("My invoice INV-77 is wrong", email="export.me@example.com")
        conv = frappe.get_doc(CONV, name)
        from thinknxg_support.integrations.conversations import post_agent_message

        post_agent_message(conv, "<p>Checking now</p>", sender="Administrator")
        post_agent_message(conv, "<p>VIP, be careful</p>", sender="Administrator", internal=1)
        other = self.chat("Unrelated", email="someone.else@example.com")
        req = self._request("Export", email="Export.Me@example.com")
        self.assertEqual(privacy.review(req.name)["conversations"], 1)
        out = privacy.run(req.name)
        data = json.loads(frappe.get_doc("File", {"file_url": out["file_url"]}).get_content())
        texts = [m["text"] for c in data["conversations"] for m in c["messages"]]
        self.assertIn("My invoice INV-77 is wrong", texts)
        self.assertIn("Checking now", texts)
        self.assertNotIn("VIP, be careful", texts)
        self.assertNotIn(other, [c["id"] for c in data["conversations"]])
        self.assertTrue(frappe.db.get_value("File", {"file_url": out["file_url"]}, "is_private"))
        self.assertEqual(frappe.db.get_value(REQ, req.name, "status"), "Completed")

    def test_erase_anonymises_but_keeps_the_numbers(self):
        name = self.chat("Call me on +968 9123 4567, I am Nadia", email="erase.me@example.com", phone="+968 9123 4567",
                         first_agent_reply_at=now_datetime())
        msg = frappe.get_all(MSG, filters={"conversation": name}, pluck="name")[0]
        f = frappe.get_doc({"doctype": "File", "file_name": "passport.txt", "content": b"x", "is_private": 1,
                            "attached_to_doctype": MSG, "attached_to_name": msg}).insert(ignore_permissions=True)
        req = self._request("Erase", phone="91234567")  # matched by phone alone
        privacy.review(req.name)
        self.assertRaises(frappe.ValidationError, privacy.run, req.name)  # no ERASE typed
        out = privacy.run(req.name, "ERASE")
        self.assertEqual(out["conversations"], 1)
        c = frappe.get_doc(CONV, name)
        self.assertIsNone(c.guest_email)
        self.assertIsNone(c.guest_phone)
        self.assertIsNone(c.guest_token_hash)
        self.assertEqual(c.guest_name, "Erased")
        self.assertTrue(c.first_agent_reply_at)  # response times stay for reports
        self.assertNotIn("Nadia", frappe.db.get_value(MSG, msg, "content"))
        self.assertFalse(frappe.db.exists("File", f.name))
        event = frappe.get_all("Support Portal Event", filters={"event_type": "Privacy Erase", "reference_name": req.name},
                               fields=["details"], limit=1)
        self.assertTrue(event)
        self.assertNotIn("9123", event[0].details or "")
        self.assertRaises(frappe.ValidationError, privacy.run, req.name, "ERASE")  # only once

    def test_unverified_or_unreviewed_requests_do_not_run(self):
        req = frappe.get_doc({"doctype": REQ, "request_type": "Export", "email": "x@example.com"}).insert()
        self.assertRaises(frappe.ValidationError, privacy.run, req.name)
        privacy.review(req.name)
        self.assertRaises(frappe.ValidationError, privacy.run, req.name)
        self.assertRaises(frappe.ValidationError, frappe.get_doc({"doctype": REQ, "request_type": "Erase"}).insert)

    def test_only_administrators_run_privacy_requests(self):
        as_user(self.manager)
        self.assertFalse(frappe.has_permission(REQ, "create"))


class TestLimits(Base):
    def test_hosting_plan_caps_and_site_limits(self):
        with patch.dict(frappe.conf, {"thinknxg_support_limits": {"guest_chats_per_day": 100}}):
            self.assertEqual(limits.limit("guest_chats_per_day"), 100)
            frappe.db.set_single_value("Support Usage Limits", "guest_chats_per_day", 10)
            self.assertEqual(limits.limit("guest_chats_per_day"), 10)
            doc = frappe.get_single("Support Usage Limits")
            doc.guest_chats_per_day = 500
            doc.save()
            self.assertEqual(frappe.db.get_single_value("Support Usage Limits", "guest_chats_per_day"), 100)
        frappe.db.set_single_value("Support Usage Limits", "guest_chats_per_day", 0)
        self.assertIsNone(limits.limit("guest_chats_per_day"))

    def test_guest_chats_stop_at_the_daily_limit(self):
        self.chat()
        used = limits.used("guest_chats_per_day")
        with patch.dict(frappe.conf, {"thinknxg_support_limits": {"guest_chats_per_day": used}}):
            self.assertRaises(frappe.ValidationError, self.chat)

    def test_ai_stops_at_the_monthly_token_limit(self):
        frappe.cache.delete_value("thinknxg_support:ai_tokens_month")
        used = limits.used("ai_tokens_per_month")
        with patch.dict(frappe.conf, {"thinknxg_support_limits": {"ai_tokens_per_month": used + 1000}}):
            self.assertTrue(providers.budget_left())
            providers.log_usage(kind="Copilot", result={"prompt_tokens": 900, "completion_tokens": 200})
            self.assertFalse(providers.budget_left())

    def test_knowledge_document_count_limit(self):
        with patch.dict(frappe.conf, {"thinknxg_support_limits": {"knowledge_documents": limits.used("knowledge_documents")}}):
            self.assertRaises(frappe.ValidationError, frappe.get_doc(
                {"doctype": "Support Knowledge Document", "title": "Over", "file": "/private/files/over.txt"}).insert)


class TestSecurity(Base):
    def test_checks_and_requiring_two_factor(self):
        keys = {c["key"] for c in security.checks()}
        self.assertTrue({"two_factor", "password_policy", "lockout", "session", "https"} <= keys)
        before = {r: frappe.db.get_value("Role", r, "two_factor_auth") for r in security.SUPPORT_ROLES}
        before_ss = frappe.db.get_single_value("System Settings", "enable_two_factor_auth")
        try:
            out = security.require_two_factor_for_support_roles()
            self.assertTrue(next(c for c in out if c["key"] == "two_factor")["ok"])
            self.assertEqual(security.staff_without_two_factor(), 0)
            self.assertTrue(frappe.get_all("Support Portal Event", filters={"details": ["like", "%two_factor_required_for%"]}))
        finally:
            for r, v in before.items():
                frappe.db.set_value("Role", r, "two_factor_auth", v or 0)
            frappe.db.set_single_value("System Settings", "enable_two_factor_auth", before_ss or 0)
