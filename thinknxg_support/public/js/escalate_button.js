// "Escalate" on Helpdesk tickets (desk form): creates a Support Escalation and alerts the team.
frappe.ui.form.on("HD Ticket", {
    refresh(frm) {
        if (frm.is_new() || !frappe.user.has_role(["Support Agent", "Support Manager", "Support Portal Administrator", "System Manager"])) return;
        frm.add_custom_button(__("Escalate"), () => thinknxgEscalate(frm), __("Support"));
    },
});

window.thinknxgEscalate = function (frm) {
    const d = new frappe.ui.Dialog({
        title: __("Escalate to the support team"),
        fields: [
            { fieldname: "priority", fieldtype: "Select", label: __("Priority"), options: ["", "Critical", "High", "Medium", "Low"] },
            { fieldname: "assign_to", fieldtype: "Link", options: "User", label: __("Assign To"),
              get_query: () => ({ filters: { user_type: "System User", enabled: 1 } }) },
            { fieldname: "note", fieldtype: "Small Text", label: __("Why"), reqd: 1 },
        ],
        primary_action_label: __("Escalate"),
        primary_action(v) {
            d.hide();
            frappe.call({ method: "thinknxg_support.integrations.escalations.escalate_document",
                args: { doctype: frm.doctype, name: frm.doc.name, ...v }, freeze: true })
                .then((r) => frappe.show_alert({ message: __("Escalated as {0}", [`<a href="/app/support-escalation/${r.message}">${r.message}</a>`]), indicator: "orange" }, 8));
        },
    });
    d.show();
};
