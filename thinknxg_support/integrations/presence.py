"""Whether an agent takes new chats now: their status, their shift and whether they are active.

effective(user) -> {"status", "reason", "note", "set_status"}:
* Offline when an enabled shift says they are off now ("Off shift"), or they set Offline.
* Away when they set Away, or (Available, with a client that reports activity) idle longer than the site's
  "Away After Idle Minutes" (Support Portal Settings; 0 switches it off).
* Busy when they set Busy. Otherwise Available.
Clients that do not report activity (older apps) are never made Away automatically.
"""
from __future__ import annotations

import datetime

import frappe
from frappe import _
from frappe.utils import cint, get_datetime, get_time, now_datetime

STATUS = "Support Agent Status"
SHIFT = "Support Agent Shift"
STATUSES = ("Available", "Away", "Busy", "Offline")
DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
P = "thinknxg_support"


def _cached(key, build, ttl=60):
    hit = frappe.cache.get_value(key)
    if hit is None:
        hit = build()
        frappe.cache.set_value(key, hit, expires_in_sec=ttl)
    return hit


def changed(user: str):
    frappe.cache.delete_value(f"{P}:agent_status:{user}")
    frappe.cache.delete_value(f"{P}:agent_shift:{user}")


def set_status_of(user: str) -> dict:
    def build():
        row = frappe.db.get_value(STATUS, user, ["status", "note", "set_on"], as_dict=True) \
            if frappe.db.exists("DocType", STATUS) else None
        return {"status": (row.status if row else None) or "Available", "note": row.note if row else None,
                "set_on": str(row.set_on) if row and row.set_on else None}

    return _cached(f"{P}:agent_status:{user}", build)


def _slots(user: str):
    def build():
        if not frappe.db.exists("DocType", SHIFT) or not frappe.db.get_value(SHIFT, {"user": user, "enabled": 1}, "name"):
            return None
        return [{"day": s.day, "start": str(s.start_time), "end": str(s.end_time)}
                for s in frappe.get_doc(SHIFT, user).slots]

    return _cached(f"{P}:agent_shift:{user}", build)


def on_shift(user: str, at=None) -> bool:
    """No enabled shift: always on. Otherwise inside one of its slots (a slot ending before it starts runs past
    midnight into the next day)."""
    slots = _slots(user)
    if slots is None:
        return True
    at = get_datetime(at or now_datetime())
    t = at.time()
    today = DAYS[at.weekday()]
    yesterday = DAYS[(at.weekday() - 1) % 7]
    for s in slots:
        start, end = get_time(s["start"]), get_time(s["end"])
        if start < end:
            if s["day"] == today and start <= t < end:
                return True
        else:  # overnight
            if (s["day"] == today and t >= start) or (s["day"] == yesterday and t < end):
                return True
    return False


def idle_minutes() -> int:
    from thinknxg_support.utils import settings

    v = settings().get("auto_away_minutes")
    return 10 if v is None else max(0, cint(v))


def mark_active(user: str):
    frappe.cache.set_value(f"{P}:active:{user}", now_datetime().isoformat(), expires_in_sec=7 * 86400)


def mark_seen(user: str):
    """A heartbeat from a client that reports activity, without activity: starts the idle clock once."""
    key = f"{P}:active:{user}"
    if frappe.cache.get_value(key) is None:
        frappe.cache.set_value(key, now_datetime().isoformat(), expires_in_sec=7 * 86400)


def last_active(user: str):
    v = frappe.cache.get_value(f"{P}:active:{user}")
    return get_datetime(v) if v else None


def effective(user: str, at=None) -> dict:
    own = set_status_of(user)
    status, reason = own["status"], None
    if not on_shift(user, at):
        status, reason = "Offline", _("Off shift")
    elif status == "Available":
        idle = idle_minutes()
        seen = last_active(user)
        if idle and seen and seen < get_datetime(at or now_datetime()) - datetime.timedelta(minutes=idle):
            status, reason = "Away", _("Idle")
    return {"status": status, "reason": reason, "note": own["note"], "set_status": own["status"]}


def takes_new_chats(user: str) -> bool:
    return effective(user)["status"] == "Available"


def rung_for_queue(user: str) -> bool:
    return effective(user)["status"] != "Offline"


def set_status(user: str, status: str, note: str | None = None) -> dict:
    if status not in STATUSES:
        frappe.throw(_("Choose Available, Away, Busy or Offline."))
    note = (note or "").strip()[:140] or None
    if frappe.db.exists(STATUS, user):
        doc = frappe.get_doc(STATUS, user)
        doc.status, doc.note = status, note
    else:
        doc = frappe.get_doc({"doctype": STATUS, "user": user, "status": status, "note": note})
    doc.flags.ignore_permissions = True
    doc.save()
    if status == "Available":
        mark_active(user)
    return effective(user)


def heartbeat(user: str, active=None):
    """active: 1 when the person used the app since the last heartbeat, 0 when not, None for older clients."""
    if active is None or active == "":
        return
    if cint(active):
        mark_active(user)
    else:
        mark_seen(user)


def team() -> list[dict]:
    """Every agent with their status now (for managers and the transfer list)."""
    from thinknxg_support.integrations import alerts, realtime

    out = []
    for u in alerts.all_agents():
        e = effective(u)
        out.append({"user": u, "name": frappe.utils.get_fullname(u), "online": bool(realtime.is_online(u)), **e})
    return sorted(out, key=lambda a: (STATUSES.index(a["status"]), (a["name"] or "").lower()))
