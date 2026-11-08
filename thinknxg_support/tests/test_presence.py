"""1.14 increment 2: agent status, shifts, priority and tags."""
from unittest.mock import patch

import frappe
from frappe.utils import add_to_date, get_datetime, now_datetime

from thinknxg_support.api.staff import v1
from thinknxg_support.integrations import live_chat, presence, routing, tags
from thinknxg_support.tests.utils import BaseTestCase, as_user

CONV = "Support Conversation Link"
Q = "Presence Test Queue"


def make_user(email, roles):
    if not frappe.db.exists("User", email):
        frappe.get_doc({"doctype": "User", "email": email, "first_name": email.split("@")[0], "send_welcome_email": 0,
                        "roles": [{"role": r} for r in roles]}).insert(ignore_permissions=True)
    return email


class Base(BaseTestCase):
    def setUp(self):
        as_user("Administrator")
        self.a = make_user("pres-a@example.com", ["Support Agent"])
        self.b = make_user("pres-b@example.com", ["Support Agent"])
        for u in (self.a, self.b):
            for dt in ("Support Agent Status", "Support Agent Shift"):
                if frappe.db.exists(dt, u):
                    frappe.delete_doc(dt, u, force=True)
            presence.changed(u)
            frappe.cache.delete_value(f"thinknxg_support:active:{u}")
        if frappe.db.exists("Support Chat Queue", Q):
            frappe.delete_doc("Support Chat Queue", Q, force=True)
        self.queue = frappe.get_doc({"doctype": "Support Chat Queue", "queue_name": Q, "assignment_rule": "Least Busy",
                                     "only_online_agents": 0,
                                     "members": [{"user": self.a, "active": 1, "max_chats": 50},
                                                 {"user": self.b, "active": 1, "max_chats": 50}]}).insert()
        frappe.db.set_single_value("Support Portal Settings", {"auto_away_minutes": 10, "enable_live_chat": 1,
                                                              "allow_guest_chat": 1, "guest_chat_rate_limit": 1000})
        frappe.clear_document_cache("Support Portal Settings", "Support Portal Settings")
        frappe.cache.delete_keys("thinknxg_support:rl:")
        from thinknxg_support.utils import clear_request_cache

        clear_request_cache()

    def tearDown(self):
        as_user("Administrator")

    def picked(self, n=6):
        q = frappe.get_doc("Support Chat Queue", Q)
        with patch.object(routing, "open_load", return_value=0):
            return {routing.pick_agent(q) for _ in range(n)}


class TestStatusAndRouting(Base):
    def test_nobody_has_a_status_or_shift_so_routing_is_unchanged(self):
        self.assertEqual(presence.effective(self.a)["status"], "Available")
        self.assertIn(self.a, self.picked())

    def test_only_available_agents_get_new_chats(self):
        for status in ("Away", "Busy", "Offline"):
            presence.set_status(self.a, status)
            self.assertEqual(self.picked(), {self.b}, status)
        presence.set_status(self.a, "Available")
        self.assertIn(self.a, self.picked())
        presence.set_status(self.a, "Busy")
        presence.set_status(self.b, "Away")
        self.assertEqual(self.picked(), {None})  # nobody: the chat waits in the queue

    def test_idle_agents_become_away_but_old_clients_never_do(self):
        presence.heartbeat(self.a, None)  # an older app: no activity reported
        self.assertEqual(presence.effective(self.a, add_to_date(now_datetime(), hours=3))["status"], "Available")
        presence.heartbeat(self.a, 1)
        later = add_to_date(now_datetime(), minutes=11)
        self.assertEqual(presence.effective(self.a, later), {"status": "Away", "reason": "Idle", "note": None,
                                                            "set_status": "Available"})
        frappe.db.set_single_value("Support Portal Settings", "auto_away_minutes", 0)
        frappe.clear_document_cache("Support Portal Settings", "Support Portal Settings")
        from thinknxg_support.utils import clear_request_cache

        clear_request_cache()
        self.assertEqual(presence.effective(self.a, later)["status"], "Available")

    def test_shifts_including_overnight(self):
        frappe.get_doc({"doctype": "Support Agent Shift", "user": self.a, "enabled": 1, "slots": [
            {"day": "Sunday", "start_time": "08:00:00", "end_time": "16:00:00"},
            {"day": "Monday", "start_time": "22:00:00", "end_time": "06:00:00"},
        ]}).insert()
        cases = {"2026-11-08 09:00:00": True,   # Sunday
                 "2026-11-08 16:00:00": False,
                 "2026-11-09 23:30:00": True,   # Monday night
                 "2026-11-10 05:59:00": True,   # Tuesday morning, same shift
                 "2026-11-10 06:00:00": False,
                 "2026-11-11 09:00:00": False}  # Wednesday
        for at, on in cases.items():
            self.assertEqual(presence.on_shift(self.a, get_datetime(at)), on, at)
        self.assertEqual(presence.effective(self.a, get_datetime("2026-11-11 09:00:00"))["reason"], "Off shift")
        self.assertTrue(presence.on_shift(self.b))  # no shift: always on

    def test_offline_agents_are_not_rung_for_queue_chats(self):
        presence.set_status(self.a, "Offline")
        self.assertFalse(presence.rung_for_queue(self.a))
        self.assertTrue(presence.rung_for_queue(self.b))

    def test_agents_set_their_own_status_through_the_api(self):
        as_user(self.a)
        out = v1.set_status("Busy", "In a meeting until 3")
        self.assertEqual((out["status"], out["note"]), ("Busy", "In a meeting until 3"))
        self.assertEqual(v1.bootstrap()["agent"]["status"]["status"], "Busy")
        self.assertRaises(frappe.ValidationError, v1.set_status, "Sleeping")
        v1.heartbeat(active=1)
        self.assertIsNotNone(presence.last_active(self.a))
        targets = {t["user"]: t for t in v1.team_status()}
        self.assertEqual(targets[self.a]["status"], "Busy")


class TestPriorityAndTags(Base):
    def chat(self, text="Hello"):
        as_user("Guest")
        with patch("thinknxg_support.integrations.ai.engine.respond"):
            r = live_chat.start_guest(text, name="Rana", email="rana@example.com")
        as_user("Administrator")
        frappe.db.set_value(CONV, r["conversation"], {"assigned_agent": self.a, "handling": "Agent"}, update_modified=False)
        return r["conversation"]

    def test_priority_is_set_by_people_and_sorts_the_inbox(self):
        low, urgent, normal = self.chat("one"), self.chat("two"), self.chat("three")
        as_user(self.a)
        v1.set_priority(low, "Low")
        out = v1.set_priority(urgent, "Urgent")
        self.assertEqual(out["priority"], "Urgent")
        self.assertRaises(frappe.ValidationError, v1.set_priority, low, "Critical")
        ids = [c["id"] for c in v1.conversations(view="mine", sort="priority", limit=50)["items"]]
        mine = [i for i in ids if i in (low, urgent, normal)]
        self.assertEqual(mine, [urgent, normal, low])
        self.assertEqual([c["id"] for c in v1.conversations(view="mine", priority="Urgent")["items"]], [urgent])
        page1 = v1.conversations(view="mine", sort="priority", limit=1)
        page2 = v1.conversations(view="mine", sort="priority", limit=1, cursor=page1["next_cursor"])
        self.assertNotEqual(page1["items"][0]["id"], page2["items"][0]["id"])  # paging keeps the order

    def test_tags_use_frappes_tags(self):
        name = self.chat()
        as_user(self.a)
        out = v1.set_tags(name, add=["refund", "VIP customer"])
        self.assertEqual(out["tags"], ["refund", "VIP customer"])
        self.assertIn("refund", frappe.db.get_value(CONV, name, "_user_tags"))
        self.assertTrue(frappe.db.exists("Tag Link", {"document_type": CONV, "document_name": name, "tag": "refund"}))
        self.assertEqual([c["id"] for c in v1.conversations(view="mine", tag="refund")["items"]], [name])
        self.assertIn("refund", v1.tag_suggestions())
        out = v1.set_tags(name, remove=["refund"])
        self.assertEqual(out["tags"], ["VIP customer"])
        self.assertEqual(tags.clean(" a, b "), "a b")

    def test_agents_without_access_cannot_change_priority_or_tags(self):
        name = self.chat()
        frappe.db.set_value(CONV, name, {"assigned_agent": None, "queue": Q}, update_modified=False)
        outsider = make_user("pres-out@example.com", ["Support Agent"])
        as_user(outsider)
        self.assertRaises(frappe.PermissionError, v1.set_priority, name, "High")
        self.assertRaises(frappe.PermissionError, v1.set_tags, name, ["x"])
