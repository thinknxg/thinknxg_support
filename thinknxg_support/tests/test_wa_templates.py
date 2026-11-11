"""1.17: WhatsApp message templates (Meta's Graph API mocked)."""
import itertools
import json
from unittest.mock import patch

import frappe
from frappe.utils import add_to_date, now_datetime

from thinknxg_support.integrations import automation, whatsapp, wa_templates
from thinknxg_support.integrations.conversations import post_agent_message
from thinknxg_support.tests.utils import BaseTestCase, as_user
from thinknxg_support.utils import clear_request_cache

IDS = itertools.count(1)
TPL, CONSENT, MSG, CONV = ("Support WhatsApp Template", "Support WhatsApp Consent", "Support Portal Message",
                           "Support Conversation Link")

TEMPLATES = {"data": [
    {"name": "order_update", "language": "en", "status": "APPROVED", "category": "UTILITY", "id": "111",
     "parameter_format": "POSITIONAL", "components": [
         {"type": "HEADER", "format": "TEXT", "text": "Order {{1}}", "example": {"header_text": ["A100"]}},
         {"type": "BODY", "text": "Hi {{1}}, your order {{2}} is on its way.", "example": {"body_text": [["Salim", "A100"]]}},
         {"type": "FOOTER", "text": "thinkNXG"},
         {"type": "BUTTONS", "buttons": [{"type": "URL", "text": "Track", "url": "https://x.example/t/{{1}}",
                                          "example": ["https://x.example/t/A100"]}]}]},
    {"name": "summer_offer", "language": "en", "status": "APPROVED", "category": "MARKETING", "id": "222",
     "components": [{"type": "BODY", "text": "Hello {{1}}, 20% off this week!", "example": {"body_text": [["Salim"]]}}]},
    {"name": "login_code", "language": "en", "status": "APPROVED", "category": "AUTHENTICATION", "id": "333",
     "components": [{"type": "BODY", "add_security_recommendation": True},
                    {"type": "BUTTONS", "buttons": [{"type": "OTP", "otp_type": "COPY_CODE", "text": "Copy code"}]}]},
    {"name": "named_tpl", "language": "ar", "status": "PENDING", "category": "UTILITY", "id": "444",
     "parameter_format": "NAMED", "components": [
         {"type": "BODY", "text": "Hello {{name}}, ticket {{ticket}}",
          "example": {"body_text_named_params": [{"param_name": "name", "example": "S"},
                                                 {"param_name": "ticket", "example": "T1"}]}}]},
]}


def fake_enqueue_factory(calls):
    def fake(fn, **kw):
        calls.append(fn)
        if fn is whatsapp.deliver:
            fn(message=kw["message"])
    return fake


class TestWhatsAppTemplates(BaseTestCase):
    def setUp(self):
        as_user("Administrator")
        for dt in (TPL, "Support WhatsApp Template Variable", CONSENT):
            frappe.db.delete(dt)
        s = frappe.get_single("Support Portal Settings")
        s.update({"enable_whatsapp": 1, "whatsapp_phone_number_id": "1234567890", "whatsapp_access_token": "tok",
                  "whatsapp_business_account_id": "WABA1", "whatsapp_app_secret": "secret-for-tests",
                  "whatsapp_verify_token": "verify-me", "enable_raven": 0, "whatsapp_template_name": "",
                  "whatsapp_auto_reply": "", "whatsapp_link_contacts": 1, "whatsapp_require_optin": 1,
                  "whatsapp_optout_reply": "You will no longer receive marketing messages from us.",
                  "whatsapp_optin_reply": "Thank you, you will receive our updates again."})
        s.flags.ignore_permissions = True
        s.save()
        clear_request_cache()
        self.n = 0

    def number(self):
        TestWhatsAppTemplates.counter = getattr(TestWhatsAppTemplates, "counter", 0) + 1
        return f"9687100{TestWhatsAppTemplates.counter:04d}"

    def sync(self, payload=None):
        with patch.object(whatsapp, "_api", lambda *a, **k: payload or TEMPLATES):
            return wa_templates.sync()

    def conv(self, closed_window=True, name="Salim Al Harthy"):
        num = self.number()
        with patch.object(whatsapp, "_send", return_value="wamid.r"):
            conv = whatsapp._open_conversation(num, name)
        conv.db_set("whatsapp_window_expires", add_to_date(now_datetime(), hours=-1 if closed_window else 5))
        return frappe.get_doc(CONV, conv.name)

    def map_order_update(self):
        t = frappe.get_doc(TPL, "order_update-en")
        src = {"header.1": ("Fixed Text", "A100"), "body.1": ("Customer First Name", None),
               "body.2": ("Fixed Text", "A100"), "button0.1": ("Fixed Text", "A100")}
        for v in t.variables:
            v.source, v.fixed_text = src[v.key]
        t.save()

    def send(self, conv, template, values=None, user="Administrator", **kw):
        sent, calls = [], []
        self.ids = []

        def fake_send(payload):
            sent.append(payload)
            self.ids.append(f"wamid.tpl{next(IDS)}")
            return self.ids[-1]

        with patch.object(whatsapp, "available", return_value=True), patch.object(whatsapp, "_send", fake_send), \
                patch.object(frappe, "enqueue", fake_enqueue_factory(calls)):
            out = wa_templates.send(conv, template, values, user=user, **kw)
        return out, sent

    # ------------------------------------------------------------------ sync
    def test_sync_reads_templates_and_their_variables(self):
        self.assertIn("4 templates", self.sync())
        t = frappe.get_doc(TPL, "order_update-en")
        self.assertEqual((t.category, t.status, t.header_text), ("Utility", "Approved", "Order {{1}}"))
        self.assertEqual([v.key for v in t.variables], ["header.1", "body.1", "body.2", "button0.1"])
        self.assertEqual(t.variables[1].example, "Salim")
        self.assertEqual(frappe.db.get_value(TPL, "named_tpl-ar", "status"), "Pending")
        self.assertEqual(frappe.get_doc(TPL, "named_tpl-ar").parameter_format, "Named")
        self.assertEqual([v.position for v in frappe.get_doc(TPL, "named_tpl-ar").variables], ["name", "ticket"])
        self.assertEqual([v.key for v in frappe.get_doc(TPL, "login_code-en").variables], ["body.1"])

    def test_sync_keeps_the_variable_map_and_marks_removed_templates(self):
        self.sync()
        self.map_order_update()
        self.sync({"data": [t for t in TEMPLATES["data"] if t["name"] != "summer_offer"]})
        t = frappe.get_doc(TPL, "order_update-en")
        self.assertEqual({v.key: v.source for v in t.variables}["body.1"], "Customer First Name")
        self.assertEqual(frappe.db.get_value(TPL, "summer_offer-en", "status"), "Deleted")

    def test_sync_follows_paging(self):
        pages = [{"data": TEMPLATES["data"][:2], "paging": {"next": "https://graph.example/next"}},
                 {"data": TEMPLATES["data"][2:]}]
        with patch.object(whatsapp, "_api", lambda *a, **k: pages.pop(0)):
            wa_templates.sync()
        self.assertEqual(frappe.db.count(TPL), 4)

    # ------------------------------------------------------------------ sending
    def test_a_template_goes_out_with_its_variables_even_when_the_window_is_closed(self):
        self.sync()
        self.map_order_update()
        conv = self.conv()
        out, sent = self.send(conv, "order_update-en", client_message_id="cid-12345678")
        p = sent[0]
        self.assertEqual((p["type"], p["template"]["name"], p["template"]["language"]["code"]), ("template", "order_update", "en"))
        comps = {c["type"]: c for c in p["template"]["components"]}
        self.assertEqual(comps["header"]["parameters"], [{"type": "text", "text": "A100"}])
        self.assertEqual([x["text"] for x in comps["body"]["parameters"]], ["Salim", "A100"])
        self.assertEqual((comps["button"]["sub_type"], comps["button"]["index"]), ("url", "0"))
        row = frappe.db.get_value(MSG, out["name"], ["wa_template", "delivery_status", "content", "client_message_id"], as_dict=True)
        self.assertEqual((row.wa_template, row.delivery_status), ("order_update-en", "Sent"))
        self.assertIn("Hi Salim, your order A100 is on its way.", row.content)
        again, sent2 = self.send(conv, "order_update-en", client_message_id="cid-12345678")
        self.assertTrue(again.get("duplicate"))
        self.assertEqual(sent2, [])

    def test_the_agent_can_change_a_variable(self):
        self.sync()
        self.map_order_update()
        out, sent = self.send(self.conv(), "order_update-en", {"body.2": "B200 "})
        self.assertEqual([x["text"] for x in sent[0]["template"]["components"][1]["parameters"]], ["Salim", "B200"])

    def test_variables_must_be_filled_and_templates_must_be_approved(self):
        self.sync()
        before = frappe.db.count(MSG, {"wa_template": ["is", "set"]})
        with self.assertRaises(wa_templates.TemplateError):
            self.send(self.conv(), "order_update-en")  # nothing mapped: the agent has to fill the values
        with self.assertRaises(wa_templates.TemplateError):
            self.send(self.conv(), "named_tpl-ar", {"body.name": "x", "body.ticket": "y"})  # still Pending in Meta
        self.assertEqual(frappe.db.count(MSG, {"wa_template": ["is", "set"]}), before)

    def test_named_parameters_carry_their_names(self):
        self.sync({"data": [dict(TEMPLATES["data"][3], status="APPROVED")]})
        _, sent = self.send(self.conv(), "named_tpl-ar", {"body.name": "Salim", "body.ticket": "T9"})
        self.assertEqual(sent[0]["template"]["components"][0]["parameters"],
                         [{"type": "text", "text": "Salim", "parameter_name": "name"},
                          {"type": "text", "text": "T9", "parameter_name": "ticket"}])

    def test_authentication_code_goes_in_the_body_and_the_button(self):
        self.sync()
        _, sent = self.send(self.conv(), "login_code-en", {"body.1": "482913"})
        comps = sent[0]["template"]["components"]
        self.assertEqual(comps[0]["parameters"], [{"type": "text", "text": "482913"}])
        self.assertEqual(comps[1], {"type": "button", "sub_type": "url", "index": "0",
                                    "parameters": [{"type": "text", "text": "482913"}]})

    def test_newlines_are_removed_from_a_value(self):
        self.assertEqual(wa_templates._clean("a\nb\t c      d"), "a b  c   d")

    # ------------------------------------------------------------------ marketing consent
    def test_marketing_needs_an_optin_and_an_optout_blocks_it(self):
        self.sync()
        conv = self.conv()
        with self.assertRaises(wa_templates.OptInRequired):
            self.send(conv, "summer_offer-en", {"body.1": "Salim"})
        with self.assertRaises(frappe.ValidationError):  # an opt-in needs a note: how did they agree?
            wa_templates.record(conv.whatsapp_number, "Opted In", "Agent", note="")
        wa_templates.record(conv.whatsapp_number, "Opted In", "Agent", note="Agreed on the phone")
        _, sent = self.send(conv, "summer_offer-en", {"body.1": "Salim"})
        self.assertEqual(len(sent), 1)
        wa_templates.record(conv.whatsapp_number, "Opted Out", "Customer Message", note="STOP")
        with self.assertRaises(wa_templates.OptInRequired):
            self.send(conv, "summer_offer-en", {"body.1": "Salim"})
        agent = frappe.get_doc({"doctype": "User", "email": "wa-agent@example.com", "first_name": "WA",
                                "send_welcome_email": 0, "roles": [{"role": "Support Agent"}]}) \
            if not frappe.db.exists("User", "wa-agent@example.com") else frappe.get_doc("User", "wa-agent@example.com")
        agent.save(ignore_permissions=True)
        with self.assertRaises(wa_templates.TemplateError):  # only a manager can undo a customer's STOP
            wa_templates.record(conv.whatsapp_number, "Opted In", "Agent", note="They said yes", user="wa-agent@example.com")
        wa_templates.record(conv.whatsapp_number, "Opted In", "Manager", note="Customer confirmed by e-mail")
        self.assertEqual(wa_templates.status_of(conv.whatsapp_number), "Opted In")

    def test_utility_templates_do_not_need_an_optin(self):
        self.sync()
        self.map_order_update()
        self.assertEqual(len(self.send(self.conv(), "order_update-en")[1]), 1)

    def test_stop_and_start_from_the_customer_update_the_list_and_skip_the_assistant(self):
        self.sync()
        num = self.number()
        calls = []
        sent = []
        msg = lambda i, t: {"id": i, "from": num, "type": "text", "text": {"body": t}}  # noqa: E731
        with patch.object(whatsapp, "available", return_value=True), \
                patch.object(whatsapp, "_send", lambda p: sent.append(p) or "wamid.x"), \
                patch.object(frappe, "enqueue", fake_enqueue_factory(calls)):
            whatsapp.process_inbound(msg("wamid.S1", "STOP"), "Salim")
            self.assertEqual(wa_templates.status_of(num), "Opted Out")
            whatsapp.process_inbound(msg("wamid.S2", " start! "), "Salim")
            self.assertEqual(wa_templates.status_of(num), "Opted In")
            respond = [c for c in calls if isinstance(c, str) and c.endswith("engine.respond")]
            self.assertEqual(respond, [])  # the assistant did not answer STOP or START
            whatsapp.process_inbound(msg("wamid.S3", "please stop calling me"), "Salim")  # a sentence is not a keyword
            self.assertEqual(wa_templates.status_of(num), "Opted In")
        texts = [p["text"]["body"] for p in sent if p.get("type") == "text"]
        self.assertTrue(any("no longer receive" in t for t in texts))
        self.assertTrue(any("receive our updates" in t for t in texts))

    # ------------------------------------------------------------------ Meta events and failures
    def test_status_events_update_the_template_and_notify_managers(self):
        self.sync()
        if not frappe.db.exists("User", "wa-mgr@example.com"):
            frappe.get_doc({"doctype": "User", "email": "wa-mgr@example.com", "first_name": "WA Mgr", "send_welcome_email": 0,
                            "roles": [{"role": "Support Manager"}]}).insert(ignore_permissions=True)
        value = {"event": "PAUSED", "message_template_id": 111, "message_template_name": "order_update",
                 "message_template_language": "en", "reason": "NONE"}
        with patch.object(frappe, "enqueue"):
            whatsapp.handle_webhook({"entry": [{"id": "WABA1", "changes": [
                {"field": "message_template_status_update", "value": value}]}]})
            whatsapp.handle_webhook({"entry": [{"id": "OTHER", "changes": [
                {"field": "message_template_status_update", "value": dict(value, event="DISABLED")}]}]})
        self.assertEqual(frappe.db.get_value(TPL, "order_update-en", "status"), "Paused")
        self.assertTrue(frappe.db.exists("Notification Log", {"for_user": "wa-mgr@example.com", "document_type": TPL,
                                                              "document_name": "order_update-en"}))
        wa_templates.on_webhook("message_template_quality_update", {
            "message_template_name": "order_update", "message_template_language": "en", "new_quality_score": "RED"})
        self.assertEqual(frappe.db.get_value(TPL, "order_update-en", "quality"), "Low")
        wa_templates.on_webhook("template_category_update", {
            "message_template_name": "order_update", "message_template_language": "en", "new_category": "MARKETING"})
        self.assertEqual(frappe.db.get_value(TPL, "order_update-en", "category"), "Marketing")

    def test_a_paused_template_is_refused_before_meta_is_called(self):
        self.sync()
        self.map_order_update()
        frappe.db.set_value(TPL, "order_update-en", "status", "Paused")
        with self.assertRaises(wa_templates.TemplateError):
            self.send(self.conv(), "order_update-en")

    def test_failed_deliveries_explain_the_meta_code_and_pause_the_template(self):
        self.sync()
        self.map_order_update()
        out, _ = self.send(self.conv(), "order_update-en")
        with patch.object(frappe, "enqueue"):
            whatsapp.update_status({"id": self.ids[0], "status": "failed", "errors": [{"code": 132015, "title": "x"}]})
        row = frappe.db.get_value(MSG, out["name"], ["delivery_status", "delivery_code", "delivery_error"], as_dict=True)
        self.assertEqual((row.delivery_status, row.delivery_code), ("Failed", 132015))
        self.assertIn("paused by Meta", row.delivery_error)
        self.assertEqual(frappe.db.get_value(TPL, "order_update-en", "status"), "Paused")

    def test_the_report_counts_by_template(self):
        self.sync()
        self.map_order_update()
        def row():
            return {r["template"]: r for r in wa_templates.report()}.get("order_update-en", {"sent": 0, "delivered": 0,
                                                                                            "read": 0, "failed": 0})

        base = row()
        self.send(self.conv(), "order_update-en")
        first = self.ids[0]
        self.send(self.conv(), "order_update-en")
        with patch.object(frappe, "enqueue"):
            whatsapp.update_status({"id": first, "status": "delivered"})
            whatsapp.update_status({"id": first, "status": "read"})
        now = row()
        self.assertEqual(now["sent"] - base["sent"], 2)
        self.assertEqual(now["delivered"] - base["delivered"], 1)
        self.assertEqual(now["read"] - base["read"], 1)
        self.assertEqual(now["failed"] - base["failed"], 0)

    def test_the_old_reengagement_setting_fills_the_synced_variables(self):
        self.sync()
        self.map_order_update()
        s = frappe.get_single("Support Portal Settings")
        s.update({"whatsapp_template_name": "order_update", "whatsapp_template_language": "en"})
        s.flags.ignore_permissions = True
        s.save()
        clear_request_cache()
        conv = self.conv()
        sent = []
        with patch.object(whatsapp, "available", return_value=True), patch.object(whatsapp, "_send", lambda p: sent.append(p) or "w"), \
                patch.object(frappe, "enqueue", fake_enqueue_factory([])):
            post_agent_message(conv, "<p>late</p>")
        self.assertEqual(sent[0]["template"]["components"][1]["parameters"][0]["text"], "Salim")

    # ------------------------------------------------------------------ automation
    def rule(self, template, tag="", **kw):
        name = f"wa rule {template} {tag} {kw.get('trigger', '')}"
        frappe.db.delete("Support Automation Rule", {"rule_name": name})
        return frappe.get_doc({"doctype": "Support Automation Rule", "rule_name": name, "trigger": "Customer Quiet",
                               "action": "Send WhatsApp Template", "whatsapp_template": template, "channel_whatsapp": 1,
                               "channel_live_chat": 0, **kw}).insert(ignore_permissions=True)

    def run_rule(self, rule, conv):
        sent, calls = [], []
        with patch.object(whatsapp, "available", return_value=True), patch.object(whatsapp, "_send", lambda p: sent.append(p) or "wamid.a"), \
                patch.object(frappe, "enqueue", fake_enqueue_factory(calls)):
            return automation.run(rule, conv), sent

    def test_a_rule_sends_a_template_and_keeps_a_closed_chat_closed(self):
        self.sync()
        self.map_order_update()
        rule = self.rule("order_update-en", trigger="Chat Closed Needing Follow-up")
        conv = self.conv()
        conv.db_set("status", "Closed")
        result, sent = self.run_rule(rule, frappe.get_doc(CONV, conv.name))
        self.assertEqual(result, "template sent")
        self.assertEqual(len(sent), 1)
        self.assertEqual(frappe.db.get_value(CONV, conv.name, "status"), "Closed")
        self.assertEqual(frappe.db.get_value(MSG, {"conversation": conv.name, "wa_template": ["is", "set"]}, "response_source"),
                         f"Automation: {rule.name}")

    def test_a_rule_skips_marketing_without_optin_and_unresolved_variables(self):
        self.sync()
        conv = self.conv()
        result, sent = self.run_rule(self.rule("summer_offer-en"), conv)
        self.assertTrue(result.startswith("skipped"), result)
        self.assertEqual(sent, [])
        result, sent = self.run_rule(self.rule("order_update-en", tag="x"), conv)  # nothing mapped yet
        self.assertTrue(result.startswith("skipped"), result)

    def test_a_rule_cannot_use_an_authentication_template(self):
        self.sync()
        with self.assertRaises(frappe.ValidationError):
            self.rule("login_code-en")

    def test_a_rule_can_send_text_while_the_window_is_open(self):
        self.sync()
        self.map_order_update()
        rule = self.rule("order_update-en", tag="y", text_when_window_open=1, message="Are you still there?")
        result, sent = self.run_rule(rule, self.conv(closed_window=False))
        self.assertEqual(result, "message sent (window open)")
        self.assertEqual(sent[0]["type"], "text")

    # ------------------------------------------------------------------ agent API
    def test_agent_api_lists_sends_and_starts_chats(self):
        from thinknxg_support.api.staff import v1

        self.sync()
        self.map_order_update()
        conv = self.conv()
        info = v1.whatsapp_templates(conv.name)
        names = {t["name"]: t for t in info["templates"]}
        self.assertEqual(set(names), {"order_update-en", "summer_offer-en", "login_code-en"})
        self.assertEqual(names["summer_offer-en"]["blocked"], "no_optin")
        self.assertIsNone(names["order_update-en"]["blocked"])
        self.assertIn("Salim", names["order_update-en"]["text"]["body"])
        sent, calls = [], []
        with patch.object(whatsapp, "available", return_value=True), patch.object(whatsapp, "_send", lambda p: sent.append(p) or "wamid.q"), \
                patch.object(frappe, "enqueue", fake_enqueue_factory(calls)):
            r = v1.send_whatsapp_template(conv.name, "order_update-en", "request-id-0001")
            self.assertEqual(r["message"]["delivery"]["status"], "Sent")
            self.assertEqual(r["message"]["template"], "order_update-en")
            self.assertTrue(v1.send_whatsapp_template(conv.name, "order_update-en", "request-id-0001")["duplicate"])
            with self.assertRaises(v1.ChannelActionRequired):
                v1.send_whatsapp_template(conv.name, "summer_offer-en", "request-id-0002", {"body.1": "Salim"})
            self.assertEqual(frappe.local.response.get("error_code"), "whatsapp_optin_required")
            v1.whatsapp_consent(conv.name, "Opted In", "Asked on the phone")
            v1.send_whatsapp_template(conv.name, "summer_offer-en", "request-id-0003", json.dumps({"body.1": "Salim"}))
            created = v1.start_whatsapp_chat(self.number(), "order_update-en", "request-id-0004", {"body.1": "Salim"})
        self.assertEqual(created["channel"], "WhatsApp")
        self.assertEqual(len(sent), 3)
