"""The portal must never take over ERPNext's /support page."""
import os

import frappe

from thinknxg_support.constants import GUEST_CHAT_ROUTE, PORTAL_ROUTE
from thinknxg_support.tests.utils import BaseTestCase


class TestRoutes(BaseTestCase):
    def test_portal_route_is_not_support(self):
        self.assertNotEqual(PORTAL_ROUTE.rstrip("/"), "/support")
        self.assertTrue(GUEST_CHAT_ROUTE.startswith(PORTAL_ROUTE + "/"))

    def test_no_rule_targets_support(self):
        rules = frappe.get_hooks("website_route_rules", app_name="thinknxg_support")
        for rule in rules:
            src = rule["from_route"].rstrip("/")
            self.assertFalse(src == "/support" or src.startswith("/support/"), rule)
            self.assertNotEqual(rule["to_route"].strip("/"), "support", rule)

    def test_no_www_file_named_support(self):
        www = frappe.get_app_path("thinknxg_support", "www")
        names = {os.path.splitext(f)[0] for f in os.listdir(www)}
        self.assertNotIn("support", names)
        self.assertFalse(os.path.isdir(os.path.join(www, "support")))
