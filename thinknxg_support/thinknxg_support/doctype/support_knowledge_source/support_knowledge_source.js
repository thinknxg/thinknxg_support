const KS = "thinknxg_support.thinknxg_support.doctype.support_knowledge_source.support_knowledge_source";
frappe.ui.form.on("Support Knowledge Source", {
    refresh(frm) {
        if (frm.is_new()) return;
        frm.add_custom_button(__("Test Connection"), () =>
            frappe.call({ method: `${KS}.test_source`, args: { name: frm.doc.name }, freeze: true, freeze_message: __("Reading the source…") })
                .then((r) => frappe.msgprint({ title: __("Source test"), message: r.message })));
        frm.add_custom_button(__("Import Now"), () =>
            frappe.call({ method: `${KS}.run_import`, args: { name: frm.doc.name } }).then((r) => frappe.show_alert(r.message)));
        frm.add_custom_button(__("Re-apply Rebrand Rules"), () =>
            frappe.call({ method: `${KS}.reapply_rules`, args: { name: frm.doc.name } }).then((r) => frappe.show_alert(r.message)));
        frm.add_custom_button(__("Review Proposals"), () =>
            frappe.set_route("List", "Support Article Import", { source: frm.doc.name }));
        if (!frm.doc.licence_confirmed) {
            frm.dashboard.set_headline(__("Confirm the source's licence (Licence and Attribution) before publishing its articles."), "orange");
        }
    },
});
