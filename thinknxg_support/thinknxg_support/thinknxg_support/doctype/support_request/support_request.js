frappe.ui.form.on("Support Request", {
    refresh(frm) {
        if (!frm.is_new() && !frm.doc.helpdesk_ticket) {
            frm.add_custom_button(__("Escalate to Helpdesk Ticket"), () => {
                frappe.call({
                    method: "thinknxg_support.thinknxg_support.doctype.support_request.support_request.escalate",
                    args: { name: frm.doc.name }, freeze: true,
                }).then(() => frm.reload_doc());
            });
        }
    },
});
