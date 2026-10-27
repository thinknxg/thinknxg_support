const AI = "thinknxg_support.thinknxg_support.doctype.support_ai_settings.support_ai_settings";
frappe.ui.form.on("Support AI Settings", {
    refresh(frm) {
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
    provider(frm) {
        if (frm.doc.provider === "Anthropic") frm.set_value("api_base_url", "https://api.anthropic.com");
        else if (frm.doc.api_base_url === "https://api.anthropic.com") frm.set_value("api_base_url", "https://api.openai.com/v1");
    },
});
