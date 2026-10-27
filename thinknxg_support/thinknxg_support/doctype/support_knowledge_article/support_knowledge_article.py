# Copyright (c) 2026, Kreatao and contributors
import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime


class SupportKnowledgeArticle(Document):
    def validate(self):
        if self.status == "Published" and not self.published_on:
            self.published_on = now_datetime()

    def on_update(self):
        frappe.enqueue("thinknxg_support.integrations.ai.retrieval.index_source", queue="long",
                       enqueue_after_commit=True, doctype=self.doctype, name=self.name)

    def on_trash(self):
        frappe.db.delete("Support Knowledge Chunk", {"source_doctype": self.doctype, "source_name": self.name})
