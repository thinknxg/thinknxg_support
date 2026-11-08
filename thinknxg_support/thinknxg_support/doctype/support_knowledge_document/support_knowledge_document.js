frappe.ui.form.on("Support Knowledge Document", {
    refresh(frm) {
        if (frm.is_new()) return;
        const colour = { Ready: "green", Failed: "red", Processing: "blue", Pending: "orange" }[frm.doc.status];
        const msg = {
            Ready: __("In the knowledge base: {0} characters.", [frm.doc.characters || 0]),
            Failed: frm.doc.error || __("The file could not be read."),
            Processing: __("Reading the file…"),
            Pending: __("Waiting to be read. Reload in a moment."),
        }[frm.doc.status];
        if (msg) frm.dashboard.set_headline(msg, colour);
        frm.add_custom_button(__("Read Again"), () =>
            frappe.call({ method: "thinknxg_support.thinknxg_support.doctype.support_knowledge_document.support_knowledge_document.reprocess",
                          args: { name: frm.doc.name } }).then((r) => { frappe.show_alert(r.message); frm.reload_doc(); }));
    },
});
