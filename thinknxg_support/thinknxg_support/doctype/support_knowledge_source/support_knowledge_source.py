# Copyright (c) 2026, Kreatao and contributors
import frappe
from frappe import _
from frappe.model.document import Document

from thinknxg_support.utils import safe_link


class SupportKnowledgeSource(Document):
    def validate(self):
        for f in ("base_url", "help_center_url"):
            v = (self.get(f) or "").strip().rstrip("/")
            if v and not v.startswith(("https://", "http://")):
                frappe.throw(_("{0} must start with https://").format(self.meta.get_label(f)))
            self.set(f, v)
        if self.source_type == "Frappe Helpdesk" and not self.base_url:
            frappe.throw(_("Enter the Helpdesk site URL."))
        if self.source_type == "Page URLs" and not (self.page_urls or "").strip():
            frappe.throw(_("Add at least one page URL."))
        tpl = self.attribution_template or ""
        for key in ("{source_url}", "{owner}", "{licence}"):
            if key not in tpl:
                frappe.throw(_("The attribution must include {0}.").format(key))
        if self.licence_url and not safe_link(self.licence_url):
            frappe.throw(_("Licence URL must start with https://"))
        seen = set()
        for r in self.rules:
            k = (r.find or "").strip().lower()
            if k in seen:
                frappe.throw(_("Rebrand rule for {0} is listed twice.").format(r.find))
            seen.add(k)
        from thinknxg_support.integrations.kb_import.rebrand import validate_link_rule

        for r in self.link_rules:
            problem = validate_link_rule(r.kind, r.find, r.replace_with, r.enabled)
            if problem:
                frappe.throw(_("Website and e-mail rule row {0}: {1}").format(r.idx, _(problem)))
        if self.has_value_changed("licence_confirmed") and self.licence_confirmed:
            from thinknxg_support.audit import log_event

            log_event("Administrative Change", reference_doctype=self.doctype, reference_name=self.name,
                      details={"licence_confirmed": self.licence, "owner": self.owner_name})


def _admin():
    frappe.only_for(["System Manager", "Support Portal Administrator"])


@frappe.whitelist(methods=["POST"])
def run_import(name: str):
    _admin()
    frappe.enqueue("thinknxg_support.integrations.kb_import.importer.run", queue="long", timeout=3600,
                   source=name, user=frappe.session.user, job_id=f"thinknxg-kb-import-{name}", deduplicate=True)
    frappe.db.set_value("Support Knowledge Source", name, "last_run_status", _("Queued"))
    return _("Import started. Proposals appear under Support Article Import as they are fetched.")


@frappe.whitelist(methods=["POST"])
def test_source(name: str):
    _admin()
    from thinknxg_support.integrations.kb_import import importer

    return importer.test(name)


@frappe.whitelist(methods=["POST"])
def relink_published(name: str):
    _admin()
    from thinknxg_support.integrations.kb_import import importer

    return importer.relink_published(name)


@frappe.whitelist(methods=["POST"])
def reapply_rules(name: str):
    _admin()
    frappe.enqueue("thinknxg_support.integrations.kb_import.importer.reapply", queue="long", source=name)
    return _("Re-applying the rebrand rules to proposals that are not published yet.")
