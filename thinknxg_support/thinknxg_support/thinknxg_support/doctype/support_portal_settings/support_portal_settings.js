frappe.ui.form.on("Support Portal Settings", {
    refresh(frm) {
        if (frm.doc.whatsapp_webhook_url) {
            frm.set_df_property("whatsapp_webhook_url", "description",
                __("Paste this URL and your Verify Token into the Meta app (WhatsApp > Configuration > Webhook) and subscribe to the 'messages' field."));
        }
        if (frm.doc.enable_whatsapp) {
            frm.add_custom_button(__("Send WhatsApp Test"), () => {
                frappe.prompt(
                    { fieldname: "to", fieldtype: "Data", label: __("Send to (with country code)"), reqd: 1 },
                    (v) => frappe.call({
                        method: "thinknxg_support.thinknxg_support.doctype.support_portal_settings.support_portal_settings.test_whatsapp",
                        args: { to: v.to }, freeze: true,
                    }).then((r) => frappe.msgprint(r.message || __("Sent"))),
                    __("WhatsApp Test"), __("Send")
                );
            });
        }
        frm.add_custom_button(__("Open Chat Console"), () => frappe.set_route("support-chat"));
        frm.add_custom_button(__("Verify Integrations"), () => {
            frappe.call({
                method: "thinknxg_support.thinknxg_support.doctype.support_portal_settings.support_portal_settings.verify_integrations",
                freeze: true,
                callback: (r) => {
                    const caps = r.message || {};
                    const rows = Object.entries(caps.summary || {}).map(
                        ([k, v]) => `<tr><td>${frappe.utils.escape_html(k)}</td><td>${frappe.utils.escape_html(String(v))}</td></tr>`
                    ).join("");
                    frappe.msgprint({ title: __("Integration Status"), message: `<table class="table table-bordered">${rows}</table>` });
                    frm.reload_doc();
                },
            });
        });
        frm.add_custom_button(__("Open Portal"), () => window.open("/thinkdesk", "_blank"));
    },
});
