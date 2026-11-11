"""Push notifications to the Agent apps through Firebase Cloud Messaging (HTTP v1).

Android receives FCM directly; iOS and macOS through APNs, configured in the same Firebase project (APNs key
uploaded there). Each push is tracked (Support Push Delivery) and retried for a few minutes when Firebase cannot
be reached; the number of waiting alerts travels as the app icon's badge.
Privacy: the lock screen only ever shows generic text. The message carries the record type and name; the app signs
in, asks the server whether this agent may open it (open_target) and only then loads anything.
The service account stays on the server (Support Agent App Settings); nothing secret ships in the apps.
"""
from __future__ import annotations

import json
import time

import frappe
from frappe import _
from frappe.utils import add_to_date, cint, now_datetime, time_diff_in_seconds

SETTINGS = "Support Agent App Settings"
DEVICE = "Support Agent Device"
DELIVERY = "Support Push Delivery"
PUSH_PLATFORMS = ["Android", "iOS", "macOS"]  # Windows has no push: the app stays in the tray
MAX_ATTEMPTS = 4
RETRY_DELAYS = [60, 120, 240]  # seconds after the 1st, 2nd and 3rd failed attempt
RETRY_WINDOW = 600  # a push older than this is no longer worth sending
KEEP_DAYS = 14
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
GENERIC_TITLE = "thinkNXG Support"
GENERIC_BODY = "New support activity"
THROTTLE_SECONDS = 30  # at most one push per agent and record in this window


def enabled() -> bool:
    if not frappe.db.exists("DocType", SETTINGS):
        return False
    s = frappe.get_cached_doc(SETTINGS)
    return bool(cint(s.enabled) and cint(s.push_enabled) and s.fcm_project_id)


def _service_account() -> dict:
    s = frappe.get_doc(SETTINGS)
    raw = s.get_password("fcm_service_account", raise_exception=False) if s.fcm_service_account else None
    if not raw:
        frappe.throw(_("Add the Firebase service account JSON in Support Agent App Settings."))
    try:
        sa = json.loads(raw)
    except ValueError:
        frappe.throw(_("The Firebase service account is not valid JSON."))
    for k in ("client_email", "private_key"):
        if not sa.get(k):
            frappe.throw(_("The Firebase service account is missing {0}.").format(k))
    return sa


def access_token() -> str:
    """OAuth token for FCM, cached for 50 minutes (Google issues 60)."""
    key = "thinknxg_support:fcm_token"
    cached = frappe.cache.get_value(key)
    if cached:
        return cached
    import jwt
    import requests

    sa = _service_account()
    now = int(time.time())
    assertion = jwt.encode({"iss": sa["client_email"], "scope": SCOPE, "aud": TOKEN_URL, "iat": now, "exp": now + 3600},
                           sa["private_key"], algorithm="RS256")
    r = requests.post(TOKEN_URL, data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion},
                      timeout=15)
    if r.status_code != 200:
        frappe.throw(_("Firebase did not accept the service account ({0}).").format(r.status_code))
    token = r.json()["access_token"]
    frappe.cache.set_value(key, token, expires_in_sec=3000)
    return token


def badge_for(user: str) -> int:
    """Alerts waiting for this agent: the number on the app icon."""
    return frappe.db.count("Support Agent Alert", {"user": user, "status": "Open"})


def message_for(token: str, data: dict, platform: str, badge: int | None = None) -> dict:
    """The FCM message: generic notification text, routing data only (strings), high priority for chats."""
    payload = {k: str(v) for k, v in (data or {}).items() if v is not None and k in ("doctype", "name", "kind", "delivery")}
    android = {"channel_id": "support_alerts_v2", "sound": "default", "tag": payload.get("name") or "support",
               "default_vibrate_timings": True, "visibility": "PUBLIC"}
    aps = {"sound": "default", "thread-id": payload.get("name") or "support"}
    if badge is not None:
        android["notification_count"] = max(int(badge), 0)
        aps["badge"] = max(int(badge), 0)
    msg = {"token": token, "notification": {"title": GENERIC_TITLE, "body": GENERIC_BODY}, "data": payload,
           "android": {"priority": "high", "notification": android},
           "apns": {"headers": {"apns-priority": "10", "apns-push-type": "alert"}, "payload": {"aps": aps}}}
    if platform == "Windows":
        msg.pop("android")
        msg.pop("apns")
    return msg


def send_to_users(users, data: dict, now: bool = False) -> dict:
    """Queue (or, with now=True, send) a push to every enabled device of these users."""
    users = [u for u in dict.fromkeys(users or []) if u and u != "Guest"]
    if not users or not enabled():
        return {"sent": 0, "skipped": "push off" if users else "no users"}
    fresh = []
    for u in users:
        key = f"thinknxg_support:push:{u}:{data.get('doctype')}:{data.get('name')}"
        if not now and frappe.cache.get_value(key):
            continue
        frappe.cache.set_value(key, 1, expires_in_sec=THROTTLE_SECONDS)
        fresh.append(u)
    if not fresh:
        return {"sent": 0, "skipped": "throttled"}
    if now:
        return deliver(fresh, data)
    frappe.enqueue("thinknxg_support.integrations.push.deliver", queue="short", enqueue_after_commit=True,
                   users=fresh, data=data)
    return {"queued": len(fresh)}


def deliver(users, data: dict) -> dict:
    """One tracked delivery per device (Support Push Delivery); what Firebase could not take now is retried."""
    devices = frappe.get_all(DEVICE, filters={"user": ["in", list(users)], "enabled": 1, "platform": ["in", PUSH_PLATFORMS]},
                             fields=["name", "user", "platform", "push_token"])
    devices = [d for d in devices if d.push_token]
    if not devices:
        return {"sent": 0, "skipped": "no devices"}
    out = {"sent": 0, "removed": 0, "failed": 0, "retrying": 0}
    badges = {}
    for d in devices:
        if d.user not in badges:
            badges[d.user] = badge_for(d.user)
        row = frappe.get_doc({"doctype": DELIVERY, "user": d.user, "device": d.name, "platform": d.platform,
                              "kind": str(data.get("kind") or "")[:140], "reference_doctype": data.get("doctype"),
                              "reference_name": data.get("name"), "attempts": 0}).insert(ignore_permissions=True)
        out[_attempt(row, d, badges[d.user])] += 1
    if out["failed"]:
        frappe.log_error(title="thinkNXG Support: push failed", message=f"{out['failed']} of {len(devices)} pushes failed")
    return out


def _attempt(row, device, badge: int | None = None) -> str:
    """Send one delivery. Returns sent / removed / failed / retrying and records it on the row."""
    import requests

    project = frappe.get_cached_doc(SETTINGS).fcm_project_id
    url = f"https://fcm.googleapis.com/v1/projects/{project}/messages:send"
    data = {"kind": row.kind, "doctype": row.reference_doctype, "name": row.reference_name, "delivery": row.name}
    status, error, code = None, None, None
    for again in (True, False):
        try:
            headers = {"Authorization": f"Bearer {access_token()}", "Content-Type": "application/json"}
            r = requests.post(url, headers=headers, timeout=15,
                              json={"message": message_for(device.push_token, data, device.platform, badge)})
            code, text = r.status_code, (r.text or "")[:500]
        except Exception as e:
            code, text = None, f"{type(e).__name__}: {e}"[:500]
        if code == 401 and again:  # the cached Google token was revoked or expired early: get a new one, once
            frappe.cache.delete_value("thinknxg_support:fcm_token")
            continue
        break
    attempts = cint(row.attempts) + 1
    values = {"attempts": attempts, "next_attempt": None}
    if code == 200:
        status = "sent"
        values.update({"status": "Sent", "sent_on": now_datetime(), "error": None})
    elif code in (400, 404) and ("UNREGISTERED" in text or "registration-token-not-registered" in text):
        status = "removed"  # app uninstalled or token rotated
        frappe.db.set_value(DEVICE, device.name, {"enabled": 0, "push_token": None})
        values.update({"status": "Token Removed", "error": text})
    elif (code is None or code == 429 or code >= 500) and attempts < MAX_ATTEMPTS \
            and time_diff_in_seconds(now_datetime(), row.creation) < RETRY_WINDOW:
        status = "retrying"
        values.update({"status": "Retrying", "error": text,
                       "next_attempt": add_to_date(now_datetime(), seconds=RETRY_DELAYS[min(attempts, len(RETRY_DELAYS)) - 1])})
    else:
        status = "failed"
        values.update({"status": "Failed", "error": text})
    frappe.db.set_value(DELIVERY, row.name, values, update_modified=False)
    return status


def retry_due():
    """Every minute: send again what Firebase could not take (network trouble, 429, 5xx). A push is only useful
    while it is fresh, so retries stop after a few minutes."""
    if not frappe.db.exists("DocType", DELIVERY) or not enabled():
        return
    rows = frappe.get_all(DELIVERY, filters={"status": "Retrying", "next_attempt": ["<=", now_datetime()]},
                          fields=["name", "user", "device", "kind", "reference_doctype", "reference_name", "attempts",
                                  "creation"], order_by="next_attempt asc", limit=200)
    for row in rows:
        device = frappe.db.get_value(DEVICE, row.device, ["name", "user", "platform", "push_token", "enabled"], as_dict=True)
        if not device or not device.enabled or not device.push_token:
            frappe.db.set_value(DELIVERY, row.name, {"status": "Failed", "next_attempt": None,
                                                     "error": "The device signed out before the push could be sent"},
                                update_modified=False)
            continue
        _attempt(row, device, badge_for(row.user))
        frappe.db.commit()  # nosemgrep: each delivery stands on its own


def opened(delivery: str, user: str) -> bool:
    row = frappe.db.get_value(DELIVERY, delivery, ["user", "status"], as_dict=True) if delivery else None
    if not row or row.user != user or row.status not in ("Sent", "Opened"):
        return False
    if row.status == "Sent":
        frappe.db.set_value(DELIVERY, delivery, {"status": "Opened", "opened_on": now_datetime()}, update_modified=False)
    return True


def purge():
    """Daily: delivery records are kept for 14 days."""
    if frappe.db.exists("DocType", DELIVERY):
        frappe.db.delete(DELIVERY, {"creation": ["<", add_to_date(now_datetime(), days=-KEEP_DAYS)]})
