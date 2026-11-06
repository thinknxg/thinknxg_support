frappe.listview_settings["Support Chat Feedback"] = {
    add_fields: ["rating", "sentiment", "resolved", "reviewed"],
    get_indicator(doc) {
        const c = { Positive: "green", Neutral: "orange", Negative: "red" }[doc.sentiment] || "gray";
        return [__(doc.sentiment || "Feedback"), c, "sentiment,=," + doc.sentiment];
    },
    formatters: {
        rating(v) {
            const n = parseInt(v || 0, 10);
            return `<span title="${n}/5" style="color:#ca8a04;letter-spacing:1px">${"★".repeat(n)}<span style="color:var(--gray-300)">${"★".repeat(5 - n)}</span></span>`;
        },
    },
};
