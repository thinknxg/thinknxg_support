# Copyright (c) 2026, Kreatao and contributors
import frappe
from frappe.model.document import Document


class SupportKnowledgeSnippet(Document):
    def on_update(self):
        frappe.enqueue("thinknxg_support.integrations.ai.retrieval.index_source", queue="long",
                       enqueue_after_commit=True, doctype=self.doctype, name=self.name)

    def on_trash(self):
        frappe.db.delete("Support Knowledge Chunk", {"source_doctype": self.doctype, "source_name": self.name})
        from thinknxg_support.integrations.ai import retrieval

        retrieval.bump_version()
