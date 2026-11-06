"""Push notifications to the Agent apps through Firebase Cloud Messaging (HTTP v1).

Android receives FCM directly; iOS through APNs, configured in the same Firebase project (APNs key uploaded there).
Privacy: the lock screen only ever shows generic text. The message carries the record type and name; the app signs
in, asks the server whether this agent may open it (open_target) and only then loads anything.
The service account stays on the server (Support Agent App Settings); nothing secret ships in the apps.
"""
from __future__ import annotations

import json
import time

import frappe
from frappe import _
from frappe.utils import cint

SETTINGS = "Support Agent App Settings"
DEVICE = "Support Agent Device"
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


def message_for(token: str, data: dict, platform: str) -> dict:
    """The FCM message: generic notification text, routing data only (strings), high priority for chats."""
    payload = {k: str(v) for k, v in (data or {}).items() if v is not None and k in ("doctype", "name", "kind")}
    msg = {"token": token, "notification": {"title": GENERIC_TITLE, "body": GENERIC_BODY}, "data": payload,
           "android": {"priority": "high", "notification": {"channel_id": "support_alerts", "tag": payload.get("name") or "support"}},
           "apns": {"headers": {"apns-priority": "10"},
                    "payload": {"aps": {"sound": "default", "thread-id": payload.get("name") or "support"}}}}
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
    import requests

    devices = frappe.get_all(DEVICE, filters={"user": ["in", list(users)], "enabled": 1, "platform": ["in", ["Android", "iOS"]]},
                             fields=["name", "platform", "push_token"])
    if not devices:
        return {"sent": 0, "skipped": "no devices"}
    project = frappe.get_cached_doc(SETTINGS).fcm_project_id
    url = f"https://fcm.googleapis.com/v1/projects/{project}/messages:send"
    headers = {"Authorization": f"Bearer {access_token()}", "Content-Type": "application/json"}
    sent, removed, failed = 0, 0, 0
    for d in devices:
        try:
            r = requests.post(url, headers=headers, json={"message": message_for(d.push_token, data, d.platform)}, timeout=15)
        except Exception:
            failed += 1
            continue
        if r.status_code == 200:
            sent += 1
        elif r.status_code in (400, 404) and ("UNREGISTERED" in r.text or "registration-token-not-registered" in r.text):
            frappe.db.set_value(DEVICE, d.name, {"enabled": 0, "push_token": None})  # app uninstalled / token rotated
            removed += 1
        else:
            failed += 1
    if failed:
        frappe.log_error(title="thinkNXG Support: push failed", message=f"{failed} of {len(devices)} pushes failed")
    return {"sent": sent, "removed": removed, "failed": failed}
