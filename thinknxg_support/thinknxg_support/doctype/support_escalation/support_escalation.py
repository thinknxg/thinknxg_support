# Copyright (c) 2026, Kreatao and contributors
import frappe
from frappe.model.document import Document


class SupportEscalation(Document):
    def validate(self):
        from thinknxg_support.integrations import escalations

        escalations.on_validate(self)

    def on_update(self):
        from thinknxg_support.integrations import escalations

        escalations.on_record_update(self)


def _doc(name, perm_type="write"):
    doc = frappe.get_doc("Support Escalation", name)
    doc.check_permission(perm_type)
    return doc


@frappe.whitelist(methods=["POST"])
def assign(name: str, user: str | None = None, team: str | None = None, note: str | None = None):
    from thinknxg_support.integrations import escalations

    return escalations.reassign(_doc(name), user or frappe.session.user, team=team, note=note)


@frappe.whitelist(methods=["POST"])
def escalate_further(name: str, user: str | None = None, priority: str | None = None, note: str | None = None):
    from thinknxg_support.integrations import escalations

    return escalations.escalate_further(_doc(name), user=user, priority=priority, note=note)


@frappe.whitelist(methods=["POST"])
def set_status(name: str, status: str, note: str | None = None):
    from thinknxg_support.integrations import escalations

    return escalations.set_status(_doc(name), status, note=note)


@frappe.whitelist(methods=["POST"])
def add_note(name: str, note: str):
    from thinknxg_support.integrations import escalations

    return escalations.add_note(_doc(name), note)


@frappe.whitelist(methods=["GET"])
def interaction_history(name: str):
    from thinknxg_support.integrations import escalations

    return escalations.interaction_history(_doc(name, "read"))
