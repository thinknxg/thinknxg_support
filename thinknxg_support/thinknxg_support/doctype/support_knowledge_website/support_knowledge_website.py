# Copyright (c) 2026, Kreatao and contributors
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt

from thinknxg_support.integrations.ai import crawler


class SupportKnowledgeWebsite(Document):
    def validate(self):
        url = crawler.normalise(self.start_url or "")
        if not url:
            frappe.throw(_("Enter the start address, beginning with https://"))
        try:
            crawler.check_url(url)
        except crawler.UnsafeURL as e:
            frappe.throw(str(e))
        self.start_url = url
        if self.is_new():
            from thinknxg_support.integrations import limits  # 1.13

            limits.check("websites")
        self.max_pages = min(max(cint(self.max_pages) or 200, 1), crawler.MAX_PAGES)
        self.max_depth = min(max(cint(self.max_depth), 0), 10)
        self.delay_seconds = max(flt(self.delay_seconds), 0.5)
        if self.language:
            self.language = self.language.strip().lower()[:8]

    def on_update(self):
        if not self.is_new() and any(self.has_value_changed(f) for f in ("enabled", "audience", "site_name")):
            frappe.enqueue("thinknxg_support.integrations.ai.crawler.reindex", queue="long",
                           enqueue_after_commit=True, website=self.name)

    def on_trash(self):
        crawler.remove_pages(self.name)


@frappe.whitelist(methods=["POST"])
def crawl_now(name: str):
    frappe.only_for(["System Manager", "Support Portal Administrator", "Support Manager"])
    frappe.get_doc("Support Knowledge Website", name).check_permission("write")
    crawler.queue(name)
    frappe.db.set_value("Support Knowledge Website", name, "last_crawl_status", _("Queued"))
    return _("Crawl started. Pages appear under Support Knowledge Web Page as they are read.")
