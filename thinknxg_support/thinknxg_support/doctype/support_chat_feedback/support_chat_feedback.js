frappe.ui.form.on("Support Chat Feedback", {
    refresh(frm) {
        const r = frm.doc.rating || 0;
        frm.page.set_indicator("★".repeat(r) + "☆".repeat(5 - r), r >= 4 ? "green" : r === 3 ? "orange" : "red");
        if (frm.doc.conversation) {
            frm.add_custom_button(__("Open Chat"), () => {
                frappe.route_options = { conversation: frm.doc.conversation };
                frappe.set_route("support-chat");
            });
        }
    },
});
