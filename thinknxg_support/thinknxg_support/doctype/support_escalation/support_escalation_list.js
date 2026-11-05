frappe.listview_settings["Support Escalation"] = {
    add_fields: ["status", "priority", "overdue", "awaiting_reply", "query_type", "assigned_to", "escalation_level"],
    filters: [["status", "not in", ["Resolved", "Closed"]]],
    get_indicator(doc) {
        if (doc.overdue && !["Resolved", "Closed"].includes(doc.status)) return [__("Overdue"), "red", "overdue,=,1"];
        const map = { New: "red", Pending: "orange", "In Progress": "blue", Resolved: "green", Closed: "gray" };
        return [__(doc.status), map[doc.status] || "gray", "status,=," + doc.status];
    },
    formatters: {
        priority(value) {
            const c = { Critical: "red", High: "orange", Medium: "blue", Low: "gray" }[value] || "gray";
            return `<span class="indicator-pill ${c}">${__(value || "")}</span>`;
        },
        subject(value, df, doc) {
            const lvl = doc.escalation_level > 1 ? ` <span class="badge badge-danger">L${doc.escalation_level}</span>` : "";
            const wait = doc.awaiting_reply ? ` <span class="text-warning" title="${__("Customer waiting")}">●</span>` : "";
            return `${frappe.utils.escape_html(value || "")}${lvl}${wait}`;
        },
    },
};
