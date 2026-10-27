"""Public landing page: audience filtering, safe links and visitor access."""
import frappe

from thinknxg_support import landing
from thinknxg_support.tests.utils import BaseTestCase, as_user
from thinknxg_support.utils import clear_request_cache, safe_link


class TestLanding(BaseTestCase):
    def setUp(self):
        as_user("Administrator")
        s = frappe.get_single("Support Portal Settings")
        s.landing_enabled = 1
        s.public_knowledge = 1
        s.set("landing_sections", [
            {"section_type": "Hero", "enabled": 1, "audience": "Everyone", "title": "Welcome"},
            {"section_type": "Custom Content", "enabled": 1, "audience": "Customers", "content": "<p>Customers only</p>"},
            {"section_type": "Custom Content", "enabled": 1, "audience": "Visitors",
             "content": "<p>Visitors</p><script>alert(1)</script>"},
            {"section_type": "Custom Content", "enabled": 0, "audience": "Everyone", "content": "<p>Hidden</p>"},
            {"section_type": "FAQ", "enabled": 1, "audience": "Everyone", "items": "Q one | A one"},
            {"section_type": "Cards", "enabled": 1, "audience": "Everyone", "items": "Docs | Read | https://example.com"},
        ])
        s.set("menu_links", [
            {"label": "Site", "url": "https://example.com", "location": "Header", "audience": "Everyone", "enabled": 1},
            {"label": "Members", "url": "/members", "location": "Header", "audience": "Customers", "enabled": 1},
            {"label": "Off", "url": "https://off.example.com", "location": "Footer", "audience": "Everyone", "enabled": 0},
        ])
        s.flags.ignore_permissions = True
        s.save()
        clear_request_cache()

    def tearDown(self):
        as_user("Administrator")

    def test_safe_link(self):
        for ok in ("https://example.com", "http://x.om/a", "/thinkdesk/knowledge", "mailto:a@b.om", "tel:+96824000000"):
            self.assertTrue(safe_link(ok), ok)
        for bad in ("javascript:alert(1)", "//evil.com", "data:text/html,x", 'https://x.om/"onmouseover=1', "", None):
            self.assertFalse(safe_link(bad), bad)

    def test_visitor_sees_only_visitor_sections(self):
        as_user("Guest")
        out = landing.build()
        self.assertEqual(out["audience"], "Visitors")
        html = " ".join(x.get("html") or "" for x in out["sections"])
        self.assertIn("Visitors", html)
        self.assertNotIn("Customers only", html)
        self.assertNotIn("Hidden", html)
        self.assertNotIn("<script", html)
        types = [x["type"] for x in out["sections"]]
        self.assertIn("FAQ", types)
        self.assertIn("Cards", types)

    def test_menu_links_by_audience(self):
        as_user("Guest")
        labels = [m["label"] for m in landing.menu_links()]
        self.assertEqual(labels, ["Site"])

    def test_bad_menu_link_rejected(self):
        s = frappe.get_single("Support Portal Settings")
        s.append("menu_links", {"label": "Bad", "url": "javascript:alert(1)", "enabled": 1})
        with self.assertRaises(frappe.ValidationError):
            s.save()

    def test_public_knowledge_toggle(self):
        from thinknxg_support.api.v1 import knowledge

        frappe.db.set_single_value("Support Portal Settings", "public_knowledge", 0)
        clear_request_cache()
        as_user("Guest")
        with self.assertRaises(frappe.AuthenticationError):
            knowledge._viewer()
