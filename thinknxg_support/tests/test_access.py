"""Acceptance tests for the portal security model.

Run: bench --site <site> run-tests --app thinknxg_support
"""
import frappe
from frappe.utils import add_days, nowdate

from thinknxg_support import security
from thinknxg_support.integrations import conversations, helpdesk
from thinknxg_support.tests.utils import (BaseTestCase, as_user, grant, make_contact, make_customer,
                                          make_user)

ALPHA, BETA = "_TX Alpha Trading LLC", "_TX Beta Services SAOC"
ALICE, BOB, MGR, NOBODY = ("alice@tx-test.om", "bob@tx-test.om", "mgr@tx-test.om", "nobody@tx-test.om")


class TestPortalAccess(BaseTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        frappe.set_user("Administrator")
        frappe.db.set_single_value("Support Portal Settings", "require_contact_link", 1)
        for c in (ALPHA, BETA):
            make_customer(c)
        for email, name in ((ALICE, "Alice"), (BOB, "Bob"), (MGR, "Mona"), (NOBODY, "Nobody")):
            make_user(email, name)
        make_contact(ALICE, [ALPHA])
        make_contact(BOB, [BETA])
        make_contact(MGR, [ALPHA])
        make_contact(NOBODY, [ALPHA])
        grant(ALICE, ALPHA, "Self")
        grant(BOB, BETA, "Self")
        grant(MGR, ALPHA, "Organization Manager")
        grant(MGR, ALPHA, "Billing")

    def tearDown(self):
        as_user("Administrator")

    # --- identity resolution
    def test_user_without_grant_is_rejected(self):
        as_user(NOBODY)
        with self.assertRaises(security.PortalAccessError):
            security.get_portal_user()

    def test_guest_is_rejected(self):
        as_user("Guest")
        with self.assertRaises(frappe.AuthenticationError):
            security.get_portal_user()

    def test_cannot_switch_to_foreign_organization(self):
        as_user(ALICE)
        pu = security.get_portal_user()
        self.assertEqual(security.resolve_organization(pu, None), ALPHA)
        with self.assertRaises(security.PortalAccessError):
            security.resolve_organization(pu, BETA)

    def test_grant_requires_contact_link(self):
        as_user("Administrator")
        grant(BOB, ALPHA, "Self")  # Bob's contact is NOT linked to Alpha
        as_user(BOB)
        pu = security.get_portal_user()
        self.assertNotIn(ALPHA, pu.customers)

    def test_expired_and_future_grants_are_ignored(self):
        as_user("Administrator")
        make_contact(ALICE, [ALPHA, BETA])
        grant(ALICE, BETA, "Billing", valid_until=add_days(nowdate(), -1))
        as_user(ALICE)
        self.assertNotIn(BETA, security.get_portal_user().customers)
        as_user("Administrator")
        grant(ALICE, BETA, "Billing", valid_from=add_days(nowdate(), 3))
        as_user(ALICE)
        self.assertNotIn(BETA, security.get_portal_user().customers)

    def test_unapproved_grant_cannot_be_enabled_by_non_admin(self):
        as_user(MGR)
        doc = frappe.get_doc({"doctype": "Support Organization Access", "user": ALICE, "customer": ALPHA,
                              "access_level": "Billing", "enabled": 1})
        with self.assertRaises(frappe.ValidationError):
            doc.insert(ignore_permissions=True)

    # --- capabilities
    def test_self_level_has_no_billing_or_org_capabilities(self):
        as_user(ALICE)
        pu = security.get_portal_user()
        self.assertTrue(pu.can("tickets.own", ALPHA))
        for cap in ("invoices.read", "tickets.organization", "members.read", "statements.read"):
            self.assertFalse(pu.can(cap, ALPHA), cap)
            with self.assertRaises(security.PortalAccessError):
                security.require_capability(pu, cap, ALPHA)

    def test_manager_capabilities_are_scoped_to_their_org(self):
        as_user(MGR)
        pu = security.get_portal_user()
        self.assertTrue(pu.can("tickets.organization", ALPHA))
        self.assertTrue(pu.can("invoices.read", ALPHA))
        self.assertFalse(pu.can("invoices.read", BETA))

    def test_denials_are_audited(self):
        as_user(ALICE)
        pu = security.get_portal_user()
        before = frappe.db.count("Support Portal Event", {"event_type": "Access Denied", "user": ALICE})
        with self.assertRaises(security.PortalAccessError):
            security.resolve_organization(pu, BETA)
        after = frappe.db.count("Support Portal Event", {"event_type": "Access Denied", "user": ALICE})
        self.assertGreater(after, before)

    # --- conversations (portal-native; no Helpdesk/Raven needed)
    def test_conversation_isolation_and_internal_notes(self):
        frappe.db.set_single_value("Support Portal Settings", "enable_raven", 0)
        as_user(ALICE)
        pu = security.get_portal_user()
        conv_name = conversations.start(pu, ALPHA, "Printer offline", "<p>Help</p>", client_message_id="t-1")["name"]
        # retry with same client id does not duplicate
        again = conversations.start(pu, ALPHA, "Printer offline", "<p>Help</p>", client_message_id="t-1")
        self.assertEqual(again["name"], conv_name)

        as_user("Administrator")
        conv = frappe.get_doc("Support Conversation Link", conv_name)
        conversations.post_agent_message(conv, "internal only", internal=1)
        conversations.post_agent_message(conv, "<p>Visible reply</p>", internal=0)

        as_user(ALICE)
        pu = security.get_portal_user()
        conv = conversations.assert_conversation(pu, conv_name, ALPHA)
        texts = [m["content"] for m in conversations.messages(pu, conv)]
        self.assertFalse(any("internal only" in (t or "") for t in texts))
        self.assertTrue(any("Visible reply" in (t or "") for t in texts))

        # Bob (other org) cannot open it by ID
        as_user(BOB)
        pu_b = security.get_portal_user()
        with self.assertRaises(security.PortalAccessError):
            conversations.assert_conversation(pu_b, conv_name, BETA)

        # A participant-only conversation is hidden from the org manager
        as_user(MGR)
        pu_m = security.get_portal_user()
        with self.assertRaises(security.PortalAccessError):
            conversations.assert_conversation(pu_m, conv_name, ALPHA)

    def test_message_dedupe_on_retry(self):
        frappe.db.set_single_value("Support Portal Settings", "enable_raven", 0)
        as_user(ALICE)
        pu = security.get_portal_user()
        conv_name = conversations.start(pu, ALPHA, "Dedupe", "<p>first</p>")["name"]
        conv = conversations.assert_conversation(pu, conv_name, ALPHA)
        r1 = conversations.post_customer_message(pu, conv, "<p>retry me</p>", client_message_id="dup-1")
        r2 = conversations.post_customer_message(pu, conv, "<p>retry me</p>", client_message_id="dup-1")
        self.assertEqual(r1["name"], r2["name"])
        self.assertEqual(frappe.db.count("Support Portal Message", {"conversation": conv_name}), 2)

    def test_html_is_sanitised(self):
        frappe.db.set_single_value("Support Portal Settings", "enable_raven", 0)
        as_user(ALICE)
        pu = security.get_portal_user()
        conv_name = conversations.start(pu, ALPHA, "XSS", '<p>hi</p><script>alert(1)</script><img src=x onerror=alert(1)>')["name"]
        content = frappe.db.get_value("Support Portal Message", {"conversation": conv_name}, "content")
        self.assertNotIn("<script", content)
        self.assertNotIn("onerror", content)

    # --- documents
    def test_download_grant_respects_org_and_capability(self):
        from thinknxg_support.api.v1 import documents

        as_user("Administrator")
        f = frappe.get_doc({"doctype": "File", "file_name": "_tx_manual.txt", "content": b"manual",
                            "is_private": 1}).insert(ignore_permissions=True)
        g = frappe.get_doc({"doctype": "Support Download Grant", "title": "Manual", "customer": ALPHA,
                            "file": f.file_url, "required_capability": "documents.read"}).insert(ignore_permissions=True)
        as_user(ALICE)  # Self level has no documents.read
        pu = security.get_portal_user()
        row = frappe.db.get_value("Support Download Grant", g.name, documents.FIELDS, as_dict=True)
        self.assertFalse(documents._usable(pu, row, ALPHA))
        as_user(MGR)
        pu = security.get_portal_user()
        self.assertTrue(documents._usable(pu, row, ALPHA))
        self.assertFalse(documents._usable(pu, row, BETA))

    # --- tickets (only when Helpdesk is installed)
    def test_ticket_id_tampering(self):
        if not frappe.db.exists("DocType", "HD Ticket"):
            self.skipTest("Helpdesk not installed")
        as_user("Administrator")
        frappe.db.set_single_value("Support Portal Settings", "enable_helpdesk", 1)
        from thinknxg_support.integrations import capabilities

        capabilities.refresh(save=True)
        bob_ticket = helpdesk.create_ticket("Bob's issue", "<p>secret</p>", BOB, customer=BETA)
        alice_ticket = helpdesk.create_ticket("Alice's issue", "<p>mine</p>", ALICE, customer=ALPHA)

        as_user(ALICE)
        pu = security.get_portal_user()
        helpdesk.assert_ticket_access(pu, alice_ticket, ALPHA)
        with self.assertRaises(security.PortalAccessError):
            helpdesk.assert_ticket_access(pu, bob_ticket, ALPHA)
        listed = [t["name"] for t in helpdesk.list_tickets(pu, ALPHA)["tickets"]]
        self.assertNotIn(int(bob_ticket) if str(bob_ticket).isdigit() else bob_ticket, listed)
        with self.assertRaises(security.PortalAccessError):
            helpdesk.list_tickets(pu, ALPHA, scope="organization")

        as_user(MGR)
        pu = security.get_portal_user()
        org = [str(t["name"]) for t in helpdesk.list_tickets(pu, ALPHA, scope="organization")["tickets"]]
        self.assertIn(str(alice_ticket), org)
        self.assertNotIn(str(bob_ticket), org)
