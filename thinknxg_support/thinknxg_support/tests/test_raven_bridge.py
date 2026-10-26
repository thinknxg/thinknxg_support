"""Raven bridge loop-prevention tests (skipped when Raven is not installed)."""
import frappe

from thinknxg_support.tests.utils import BaseTestCase


class TestRavenBridge(BaseTestCase):
    def test_bot_and_bridge_messages_are_ignored(self):
        from thinknxg_support.integrations import raven

        class Msg(frappe._dict):
            pass

        frappe.flags[raven.BRIDGE_FLAG] = True
        try:
            # must return without touching the database
            self.assertIsNone(raven.on_raven_message(Msg(name="x", is_bot_message=0, channel_id="none")))
        finally:
            frappe.flags[raven.BRIDGE_FLAG] = False
        self.assertIsNone(raven.on_raven_message(Msg(name="y", is_bot_message=1, channel_id="none")))

    def test_prefix_strip(self):
        from thinknxg_support.integrations.raven import _strip_prefix

        self.assertEqual(_strip_prefix("<p>/r Hello</p>", "/r"), "<p> Hello</p>")
