const PR = "thinknxg_support.thinknxg_support.doctype.support_privacy_request.support_privacy_request";
frappe.ui.form.on("Support Privacy Request", {
    refresh(frm) {
        if (frm.is_new() || frm.doc.status === "Completed") {
            if (frm.doc.status === "Completed") frm.dashboard.set_headline(__("Completed on {0}.", [frappe.datetime.str_to_user(frm.doc.completed_on)]), "green");
            return;
        }
        frm.add_custom_button(__("Find Chats"), () =>
            frappe.call({ method: `${PR}.review`, args: { name: frm.doc.name }, freeze: true }).then((r) => {
                frm.reload_doc();
                frappe.msgprint({ title: __("Found"), message: r.message.summary });
            }));
        if (frm.doc.status !== "Reviewed") return;
        if (frm.doc.request_type === "Export") {
            frm.add_custom_button(__("Create Export"), () =>
                frappe.call({ method: `${PR}.run`, args: { name: frm.doc.name }, freeze: true }).then(() => frm.reload_doc()), __("Run"));
        } else {
            frm.add_custom_button(__("Erase Personal Data"), () => {
                frappe.prompt({ fieldname: "confirm", fieldtype: "Data", reqd: 1,
                                label: __("Type ERASE to remove this person's data from {0} chats. This cannot be undone.", [frm.doc.conversations]) },
                    (v) => frappe.call({ method: `${PR}.run`, args: { name: frm.doc.name, confirm: v.confirm }, freeze: true })
                        .then(() => frm.reload_doc()), __("Erase personal data"), __("Erase"));
            }, __("Run"));
        }
    },
});
