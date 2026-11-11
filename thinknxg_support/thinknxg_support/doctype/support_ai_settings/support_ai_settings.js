const AI = "thinknxg_support.thinknxg_support.doctype.support_ai_settings.support_ai_settings";
frappe.ui.form.on("Support AI Settings", {
    refresh(frm) {
        frm.trigger("render_sources");
        frm.add_custom_button(__("Test Connection"), () =>
            frappe.call({ method: `${AI}.test_connection`, freeze: true, freeze_message: __("Calling the model…") })
                .then((r) => frappe.msgprint({ title: __("Connection"), message: frappe.utils.escape_html(r.message || "") })));
        frm.add_custom_button(__("Rebuild Knowledge Index"), () =>
            frappe.call({ method: `${AI}.rebuild_index` }).then((r) => frappe.show_alert(r.message)));
        frm.add_custom_button(__("Try a Question"), () => {
            const d = new frappe.ui.Dialog({
                title: __("Try a question"),
                fields: [
                    { fieldname: "question", fieldtype: "Small Text", label: __("Customer question"), reqd: 1 },
                    { fieldname: "audience", fieldtype: "Select", label: __("Ask as"), options: "Everyone\nCustomers", default: "Everyone" },
                    { fieldname: "result", fieldtype: "HTML" },
                ],
                primary_action_label: __("Ask"),
                primary_action(v) {
                    d.get_field("result").$wrapper.html(`<p class="text-muted">${__("Thinking…")}</p>`);
                    frappe.call({ method: `${AI}.try_question`, args: v }).then((r) => {
                        const x = r.message || {}, esc = frappe.utils.escape_html;
                        const src = (x.sources || []).map((s) => `<li>${esc(s.title)} <span class="text-muted">(${(s.score || 0).toFixed(2)})</span></li>`).join("");
                        d.get_field("result").$wrapper.html(`
                            <div class="mb-2"><b>${__("Outcome")}:</b> ${esc(x.outcome || "")}</div>
                            ${x.answer ? `<div class="mb-2" style="padding:10px;border:1px solid var(--border-color);border-radius:8px">${x.answer}</div>` : ""}
                            ${x.confidence ? `<div><b>${__("Confidence")}:</b> ${esc(x.confidence)}</div>` : ""}
                            <div><b>${__("Passages found")}:</b><ul>${src || `<li>${__("None")}</li>`}</ul></div>
                            ${x.usage ? `<div class="text-muted small">${esc(x.usage)}</div>` : ""}`);
                    });
                },
            });
            d.show();
        });
    },
    render_sources(frm) {
        const w = frm.get_field("sources_html").$wrapper;
        w.html(`<p class="text-muted">${__("Loading…")}</p>`);
        frappe.call({ method: `${AI}.knowledge_sources` }).then((r) => {
            const esc = frappe.utils.escape_html, rows = r.message || [];
            const colour = { Active: "green", Off: "gray", Working: "blue", Problem: "red", Empty: "orange" };
            const body = rows.map((x) => `<tr>
                <td>${x.route ? `<a href="${esc(x.route)}">${esc(x.label)}</a>` : esc(x.label)}<div class="text-muted small">${esc(x.detail || "")}</div></td>
                <td>${esc(__(x.type))}</td>
                <td><span class="indicator-pill ${colour[x.state] || "gray"}">${esc(__(x.state))}</span></td>
                <td>${esc(__(x.priority || "Normal"))}</td>
                <td class="text-right">${x.items}</td>
                <td class="text-right">${x.passages}</td>
                <td>${x.last ? esc(frappe.datetime.prettyDate(x.last)) : ""}</td>
                <td class="small ${x.errors ? "text-danger" : "text-muted"}">${esc(x.note || "")}</td></tr>`).join("");
            w.html(`<table class="table table-bordered" style="margin-bottom:8px"><thead><tr>
                <th>${__("Source")}</th><th>${__("Type")}</th><th>${__("Status")}</th><th>${__("Priority")}</th>
                <th class="text-right">${__("Items")}</th><th class="text-right">${__("Passages")}</th>
                <th>${__("Last indexed")}</th><th>${__("Notes")}</th></tr></thead><tbody>${body}</tbody></table>
                <button class="btn btn-xs btn-default" data-new="Support Knowledge Website">${__("Add website source")}</button>
                <button class="btn btn-xs btn-default" data-new="Support Knowledge Document">${__("Upload document")}</button>
                <button class="btn btn-xs btn-default" data-refresh="1">${__("Refresh")}</button>`);
            w.find("[data-new]").on("click", (e) => frappe.new_doc(e.currentTarget.dataset.new));
            w.find("[data-refresh]").on("click", () => frm.trigger("render_sources"));
        });
    },
    provider(frm) {
        if (frm.doc.provider === "Anthropic") frm.set_value("api_base_url", "https://api.anthropic.com");
        else if (frm.doc.api_base_url === "https://api.anthropic.com") frm.set_value("api_base_url", "https://api.openai.com/v1");
    },
});
