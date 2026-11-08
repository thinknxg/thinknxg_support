frappe.ui.form.on("Support Usage Limits", {
    refresh(frm) {
        frappe.call({ method: "thinknxg_support.api.v1.analytics.usage", type: "GET" }).then((r) => {
            const rows = (r.message || []).map((x) => `<tr><td>${frappe.utils.escape_html(x.label)}</td>
                <td class="text-right">${x.used.toLocaleString()}</td>
                <td class="text-right">${x.limit == null ? __("No limit") : x.limit.toLocaleString()}</td>
                <td class="text-right">${x.plan == null ? "—" : x.plan.toLocaleString()}</td></tr>`).join("");
            frm.get_field("plan_html").$wrapper.html(`<table class="table table-bordered table-sm">
                <thead><tr><th>${__("Limit")}</th><th class="text-right">${__("Used")}</th>
                <th class="text-right">${__("In force")}</th><th class="text-right">${__("Hosting plan")}</th></tr></thead>
                <tbody>${rows}</tbody></table>`);
        });
    },
});
