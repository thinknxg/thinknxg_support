frappe.ui.form.on("Support Knowledge Website", {
    refresh(frm) {
        if (frm.is_new()) return;
        frm.add_custom_button(__("Crawl Now"), () =>
            frappe.call({ method: "thinknxg_support.thinknxg_support.doctype.support_knowledge_website.support_knowledge_website.crawl_now",
                          args: { name: frm.doc.name } }).then((r) => { frappe.show_alert(r.message); frm.reload_doc(); }));
        frm.add_custom_button(__("Pages"), () => frappe.set_route("List", "Support Knowledge Web Page", { website: frm.doc.name }));
        if (frm.doc.last_crawl_status) frm.dashboard.set_headline(frm.doc.last_crawl_status);
    },
});
