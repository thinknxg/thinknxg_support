frappe.query_reports["Live Chat Performance"] = {
    filters: [
        { fieldname: "from_date", label: __("From"), fieldtype: "Date", default: frappe.datetime.add_days(frappe.datetime.get_today(), -30), reqd: 1 },
        { fieldname: "to_date", label: __("To"), fieldtype: "Date", default: frappe.datetime.get_today(), reqd: 1 },
        { fieldname: "channel", label: __("Channel"), fieldtype: "Select", options: "\nLive Chat\nWhatsApp\nPortal" },
    ],
};
