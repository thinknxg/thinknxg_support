frappe.query_reports["Agent Alert Response"] = {
    filters: [
        { fieldname: "from_date", label: __("From"), fieldtype: "Date", default: frappe.datetime.add_days(frappe.datetime.get_today(), -7), reqd: 1 },
        { fieldname: "to_date", label: __("To"), fieldtype: "Date", default: frappe.datetime.get_today(), reqd: 1 },
        { fieldname: "user", label: __("Agent"), fieldtype: "Link", options: "User" },
        { fieldname: "kind", label: __("Activity"), fieldtype: "Select", options: ["", "New Chat", "Chat Message", "New Ticket", "Ticket Assigned", "Conversation Message", "Escalation"] },
    ],
};
