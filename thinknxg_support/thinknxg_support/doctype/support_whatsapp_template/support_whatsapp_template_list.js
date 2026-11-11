frappe.listview_settings["Support WhatsApp Template"] = {
    onload(list) {
        list.page.add_inner_button(__("Sync from Meta"), () =>
            frappe.call({
                method: "thinknxg_support.thinknxg_support.doctype.support_whatsapp_template.support_whatsapp_template.sync_templates",
                freeze: true, freeze_message: __("Reading your templates from WhatsApp…"),
            }).then((r) => { frappe.msgprint(r.message || __("Done")); list.refresh(); }));
    },
    get_indicator(doc) {
        const c = { Approved: "green", Pending: "blue", "In Appeal": "blue", Paused: "orange", Rejected: "red", Disabled: "red", Deleted: "gray" };
        return [__(doc.status), c[doc.status] || "gray", "status,=," + doc.status];
    },
};
