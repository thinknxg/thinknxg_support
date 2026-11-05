const ESC = "thinknxg_support.thinknxg_support.doctype.support_escalation.support_escalation";
const PRIO_COLOR = { Critical: "red", High: "orange", Medium: "blue", Low: "gray" };

function act(frm, method, args, msg) {
    return frappe.call({ method: `${ESC}.${method}`, args: { name: frm.doc.name, ...args }, freeze: true })
        .then(() => { if (msg) frappe.show_alert({ message: msg, indicator: "green" }); frm.reload_doc(); });
}

frappe.ui.form.on("Support Escalation", {
    refresh(frm) {
        if (frm.is_new()) return;
        const d = frm.doc, open = !["Resolved", "Closed"].includes(d.status);
        if (d.overdue && open) {
            frm.dashboard.set_headline(__("Overdue: {0}", [d.response_overdue && !d.first_response_on
                ? __("no first response by {0}", [frappe.datetime.str_to_user(d.response_due)])
                : __("not resolved by {0}", [frappe.datetime.str_to_user(d.resolution_due)])]), "red");
        } else if (d.awaiting_reply && open) {
            frm.dashboard.set_headline(__("The customer is waiting for a reply."), "orange");
        }
        frm.page.set_indicator(__(d.priority), PRIO_COLOR[d.priority] || "gray");

        // Open the query where it lives
        if (d.reference_doctype === "Support Conversation Link") {
            frm.add_custom_button(__("Open in Support Chat"), () => {
                frappe.route_options = { conversation: d.reference_name };
                frappe.set_route("support-chat");
            });
        }
        if (d.reference_name) {
            frm.add_custom_button(__("Open {0}", [__(d.reference_doctype)]), () =>
                frappe.set_route("Form", d.reference_doctype, d.reference_name));
        }
        if (d.related_ticket) {
            frm.add_custom_button(__("Open Helpdesk Ticket"), () => window.open(`/helpdesk/tickets/${d.related_ticket}`));
        }

        if (open) {
            if (d.assigned_to !== frappe.session.user) {
                frm.add_custom_button(__("Assign to Me"), () => act(frm, "assign", { user: frappe.session.user }, __("Assigned to you")), __("Actions"));
            }
            frm.add_custom_button(__("Reassign"), () => {
                const dlg = new frappe.ui.Dialog({
                    title: __("Reassign"),
                    fields: [
                        { fieldname: "user", fieldtype: "Link", options: "User", label: __("Assign To"), reqd: 1,
                          get_query: () => ({ filters: { user_type: "System User", enabled: 1 } }) },
                        { fieldname: "team", fieldtype: "Link", options: "Support Chat Queue", label: __("Team"), default: d.team },
                        { fieldname: "note", fieldtype: "Small Text", label: __("Note for the team") },
                    ],
                    primary_action_label: __("Reassign"),
                    primary_action: (v) => { dlg.hide(); act(frm, "assign", v, __("Reassigned")); },
                });
                dlg.show();
            }, __("Actions"));
            frm.add_custom_button(__("Escalate Further"), () => {
                const dlg = new frappe.ui.Dialog({
                    title: __("Escalate Further"),
                    fields: [
                        { fieldname: "priority", fieldtype: "Select", options: ["Critical", "High", "Medium", "Low"], label: __("Priority"), default: d.priority },
                        { fieldname: "user", fieldtype: "Link", options: "User", label: __("Escalate To"),
                          get_query: () => ({ filters: { user_type: "System User", enabled: 1 } }) },
                        { fieldname: "note", fieldtype: "Small Text", label: __("Reason"), reqd: 1 },
                    ],
                    primary_action_label: __("Escalate"),
                    primary_action: (v) => { dlg.hide(); act(frm, "escalate_further", v, __("Escalated to level {0}", [(d.escalation_level || 1) + 1])); },
                });
                dlg.show();
            }, __("Actions"));
            if (d.status !== "In Progress") {
                frm.add_custom_button(__("Mark In Progress"), () => act(frm, "set_status", { status: "In Progress" }), __("Status"));
            }
            frm.add_custom_button(__("Resolve"), () => frappe.prompt(
                { fieldname: "note", fieldtype: "Small Text", label: __("Resolution note") },
                (v) => act(frm, "set_status", { status: "Resolved", note: v.note }, __("Resolved")), __("Resolve")), __("Status"));
        }
        if (d.status === "Resolved") {
            frm.add_custom_button(__("Close"), () => act(frm, "set_status", { status: "Closed" }), __("Status"));
        }
        if (!open) {
            frm.add_custom_button(__("Reopen"), () => act(frm, "set_status", { status: "Pending" }, __("Reopened")), __("Status"));
        }
        frm.add_custom_button(__("Add Internal Note"), () => frappe.prompt(
            { fieldname: "note", fieldtype: "Small Text", label: __("Note"), reqd: 1 },
            (v) => act(frm, "add_note", { note: v.note }, __("Note added")), __("Internal Note")), __("Actions"));

        frm.get_field("history_html").$wrapper.html(`<div class="text-muted small">${__("Loading…")}</div>`);
        frappe.call({ method: `${ESC}.interaction_history`, args: { name: d.name }, type: "GET" })
            .then((r) => frm.get_field("history_html").$wrapper.html(r.message || ""));
    },
});
