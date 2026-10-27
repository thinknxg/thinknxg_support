# Copyright (c) 2026, Kreatao and contributors
import frappe
from frappe import _
from frappe.model.document import Document


class SupportAISettings(Document):
    def validate(self):
        if self.enable_ai:
            if not self.model:
                frappe.throw(_("Enter the model name before enabling the assistant."))
            if not self.get_password("api_key", raise_exception=False) and "localhost" not in (self.api_base_url or "") \
                    and "127.0.0.1" not in (self.api_base_url or ""):
                frappe.throw(_("Enter the API key before enabling the assistant."))
        if self.use_embeddings and not self.embedding_model:
            frappe.throw(_("Enter the embedding model, or turn off embeddings."))
        if not (0 <= (self.min_relevance or 0) <= 1):
            frappe.throw(_("Minimum relevance must be between 0 and 1."))
        if not (0 <= (self.temperature or 0) <= 2):
            frappe.throw(_("Temperature must be between 0 and 2."))
        self.top_k = min(max(self.top_k or 4, 1), 10)
        self.chunk_size = min(max(self.chunk_size or 900, 300), 3000)
        self.timeout_seconds = min(max(self.timeout_seconds or 30, 5), 120)
        if self.provider == "Anthropic" and (self.api_base_url or "").rstrip("/") in ("", "https://api.openai.com/v1"):
            self.api_base_url = "https://api.anthropic.com"

    def on_update(self):
        from thinknxg_support.audit import log_event

        changed = [f for f in ("enable_ai", "provider", "model", "api_base_url", "use_embeddings",
                               "embedding_model", "answer_guests") if self.has_value_changed(f)]
        if changed:
            log_event("Administrative Change", reference_doctype=self.doctype, reference_name=self.name,
                      details={"changed": changed})
        if self.has_value_changed("embedding_model") or self.has_value_changed("use_embeddings"):
            frappe.enqueue("thinknxg_support.integrations.ai.retrieval.rebuild", queue="long",
                           enqueue_after_commit=True)
        frappe.clear_document_cache(self.doctype, self.name)


def _admin():
    frappe.only_for(["System Manager", "Support Portal Administrator"])


@frappe.whitelist(methods=["POST"])
def test_connection():
    _admin()
    from thinknxg_support.integrations.ai import providers

    return providers.test()


@frappe.whitelist(methods=["POST"])
def rebuild_index():
    _admin()
    frappe.enqueue("thinknxg_support.integrations.ai.retrieval.rebuild", queue="long")
    return _("Rebuilding the knowledge index in the background.")


@frappe.whitelist(methods=["POST"])
def try_question(question: str, audience: str = "Everyone"):
    frappe.only_for(["System Manager", "Support Portal Administrator", "Support Manager"])
    from thinknxg_support.integrations.ai import engine

    return engine.dry_run(question, audience)
