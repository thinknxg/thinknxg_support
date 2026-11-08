# Copyright (c) 2026, Kreatao and contributors
import frappe
from frappe import _
from frappe.model.document import Document

from thinknxg_support.integrations.ai import documents


class SupportKnowledgeDocument(Document):
    def validate(self):
        ext = documents.ext_of(self.file)
        if ext not in documents.TYPES:
            frappe.throw(_("Upload a PDF, Word (.docx), Excel (.xlsx), CSV, text, Markdown or HTML file."))
        self.file_type = ext
        if self.language:
            self.language = self.language.strip().lower()[:8]
        if self.is_new() or self.has_value_changed("file"):
            self.status = "Pending"

    def on_update(self):
        documents.make_private(self)
        if self.status == "Pending":
            frappe.enqueue("thinknxg_support.integrations.ai.documents.process", queue="long", timeout=1800,
                           enqueue_after_commit=True, name=self.name)
        elif any(self.has_value_changed(f) for f in ("enabled", "audience", "title")):
            frappe.enqueue("thinknxg_support.integrations.ai.retrieval.index_source", queue="long",
                           enqueue_after_commit=True, doctype=self.doctype, name=self.name)

    def on_trash(self):
        frappe.db.delete("Support Knowledge Chunk", {"source_doctype": self.doctype, "source_name": self.name})
        from thinknxg_support.integrations.ai import retrieval

        retrieval.bump_version()


@frappe.whitelist(methods=["POST"])
def reprocess(name: str):
    frappe.only_for(["System Manager", "Support Portal Administrator", "Support Manager"])
    doc = frappe.get_doc("Support Knowledge Document", name)
    doc.check_permission("write")
    doc.db_set({"status": "Pending", "error": None}, update_modified=False)
    frappe.enqueue("thinknxg_support.integrations.ai.documents.process", queue="long", timeout=1800,
                   enqueue_after_commit=True, name=name)
    return _("Reading the file again. The status changes to Ready when it is in the knowledge base.")
