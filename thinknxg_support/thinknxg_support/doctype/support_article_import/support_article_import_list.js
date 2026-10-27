const AIL = "thinknxg_support.thinknxg_support.doctype.support_article_import.support_article_import";
frappe.listview_settings["Support Article Import"] = {
    get_indicator(doc) {
        const map = { Proposed: "blue", "Needs Review": "orange", Approved: "green", Published: "green",
            Rejected: "gray", "Source Changed": "purple" };
        return [__(doc.status), map[doc.status] || "gray", "status,=," + doc.status];
    },
    onload(list) {
        list.page.add_action_item(__("Approve and Publish"), () => {
            const names = list.get_checked_items(true);
            if (!names.length) return;
            frappe.confirm(__("Publish {0} articles?", [names.length]), () =>
                frappe.call({ method: `${AIL}.publish`, args: { names }, freeze: true, freeze_message: __("Publishing…") })
                    .then((r) => { frappe.msgprint(r.message); list.refresh(); }));
        });
        list.page.add_action_item(__("Reject"), () => {
            const names = list.get_checked_items(true);
            if (names.length) frappe.call({ method: `${AIL}.reject`, args: { names } }).then(() => list.refresh());
        });
    },
};
