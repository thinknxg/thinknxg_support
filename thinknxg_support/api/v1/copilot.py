"""Agent copilot for the web console. Same checks as the console's own API: staff role + conversation permission."""
from __future__ import annotations

import frappe
from frappe import _

from thinknxg_support.api.v1.agent import _doc
from thinknxg_support.integrations.ai import common, copilot


def _run(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except common.Unavailable as e:
        frappe.throw(_(str(e)), title=_("AI copilot unavailable"))


@frappe.whitelist(methods=["POST"])
def suggest(name):
    return _run(copilot.suggest_replies, _doc(name))


@frappe.whitelist(methods=["POST"])
def rewrite(name, text, style="professional"):
    return _run(copilot.rewrite, text, style, _doc(name))


@frappe.whitelist(methods=["POST"])
def summarize(name):
    return _run(copilot.summarize, _doc(name))


@frappe.whitelist(methods=["POST"])
def recommend(name):
    return _run(copilot.recommend, _doc(name))


@frappe.whitelist(methods=["POST"])
def translate(name, text, target="en"):
    return _run(copilot.translate, text, target, _doc(name))


@frappe.whitelist(methods=["POST"])
def note(name):
    return _run(copilot.auto_note, _doc(name, "write"))


@frappe.whitelist(methods=["GET"])
def insight(name):
    doc = _doc(name)
    return {k: doc.get(k) for k in ("sentiment", "urgency", "intent", "customer_language", "summary", "summary_on")}
