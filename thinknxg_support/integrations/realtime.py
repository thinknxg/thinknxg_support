"""Short-lived chat state in Redis: change versions, typing, AI streaming text and agent presence.

Agents get pushes over Frappe's websocket (publish_realtime). Customer and guest widgets read this state
through a light endpoint that never touches message tables unless the version changed.
"""
from __future__ import annotations

import json
import time
import uuid

import frappe

P = "thinknxg_support:rt"


def bump(conversation: str):
    frappe.cache.set_value(f"{P}:v:{conversation}", uuid.uuid4().hex[:12], expires_in_sec=86400 * 3)


def version(conversation: str) -> str:
    return frappe.cache.get_value(f"{P}:v:{conversation}") or "0"


def set_typing(conversation: str, who: str, name: str | None = None):
    frappe.cache.set_value(f"{P}:typing:{conversation}:{who}", name or "1", expires_in_sec=6)


def typing(conversation: str, who: str):
    return frappe.cache.get_value(f"{P}:typing:{conversation}:{who}")


def stream_start(conversation: str):
    frappe.cache.set_value(f"{P}:ai:{conversation}", json.dumps({"pending": True, "text": "", "t": time.time()}),
                           expires_in_sec=180)
    bump(conversation)


_last = {}


def stream_update(conversation: str, text: str, force=False):
    now = time.monotonic()
    if not force and now - _last.get(conversation, 0) < 0.25:
        return
    _last[conversation] = now
    frappe.cache.set_value(f"{P}:ai:{conversation}", json.dumps({"pending": True, "text": text}), expires_in_sec=180)


def stream_end(conversation: str):
    frappe.cache.delete_value(f"{P}:ai:{conversation}")
    _last.pop(conversation, None)
    bump(conversation)


def stream_state(conversation: str) -> dict | None:
    raw = frappe.cache.get_value(f"{P}:ai:{conversation}")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def heartbeat(user: str):
    frappe.cache.set_value(f"{P}:presence:{user}", 1, expires_in_sec=90)


def is_online(user: str) -> bool:
    return bool(frappe.cache.get_value(f"{P}:presence:{user}"))


def live_state(conv) -> dict:
    """What a customer widget needs between full refreshes."""
    agent = typing(conv.name, "agent")
    st = stream_state(conv.name)
    return {
        "v": version(conv.name),
        "status": conv.status,
        "handling": conv.get("handling") or "",
        "agent_typing": bool(agent),
        "agent_name": (agent if isinstance(agent, str) and agent != "1" else None),
        "ai": {"pending": True, "text": (st or {}).get("text", "")} if st else None,
    }
