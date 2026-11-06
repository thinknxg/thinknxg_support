frappe.query_reports["Agent CSAT"] = {
    filters: [
        { fieldname: "from_date", label: __("From"), fieldtype: "Date", default: frappe.datetime.add_months(frappe.datetime.get_today(), -1), reqd: 1 },
        { fieldname: "to_date", label: __("To"), fieldtype: "Date", default: frappe.datetime.get_today(), reqd: 1 },
        { fieldname: "period", label: __("Group by"), fieldtype: "Select", options: ["Agent", "Agent and Week", "Agent and Month"], default: "Agent" },
        { fieldname: "agent", label: __("Agent"), fieldtype: "Link", options: "User" },
        { fieldname: "queue", label: __("Queue"), fieldtype: "Link", options: "Support Chat Queue" },
    ],
    formatter(value, row, column, data, default_formatter) {
        value = default_formatter(value, row, column, data);
        if (column.fieldname === "csat" && data && data.csat != null) {
            const c = data.csat >= 80 ? "green" : data.csat >= 60 ? "orange" : "red";
            value = `<span style="color:var(--${c}-600);font-weight:600">${value}</span>`;
        }
        return value;
    },
};
