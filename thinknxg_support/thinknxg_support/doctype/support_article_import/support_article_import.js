const AI_ = "thinknxg_support.thinknxg_support.doctype.support_article_import.support_article_import";
frappe.ui.form.on("Support Article Import", {
    refresh(frm) {
        if (frm.is_new()) return;
        frappe.call({ method: `${AI_}.preview`, args: { name: frm.doc.name }, type: "GET" }).then((r) => {
            frm.get_field("preview_html").$wrapper.html(r.message || "");
        });
        if (!["Published", "Rejected"].includes(frm.doc.status) || frm.doc.status === "Source Changed") {
            frm.add_custom_button(frm.doc.target_name ? __("Approve and Update Article") : __("Approve and Publish"), () =>
                frm.save().then(() => frappe.call({ method: `${AI_}.publish`, args: { names: frm.doc.name }, freeze: true })
                    .then((r) => { frappe.msgprint(r.message); frm.reload_doc(); })));
            frm.add_custom_button(__("Reject"), () =>
                frappe.call({ method: `${AI_}.reject`, args: { names: frm.doc.name } }).then(() => frm.reload_doc()));
        }
        if (frm.doc.target_name) {
            frm.add_custom_button(__("Open Published Article"), () => frappe.set_route("Form", frm.doc.target_doctype, frm.doc.target_name));
        }
    },
});
