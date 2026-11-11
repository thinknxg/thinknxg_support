frappe.ui.form.on("Support Portal Settings", {
    refresh(frm) {
        if (frm.doc.whatsapp_webhook_url) {
            frm.set_df_property("whatsapp_webhook_url", "description",
                __("Paste this URL and your Verify Token into the Meta app (WhatsApp > Configuration > Webhook) and subscribe to the 'messages' field, plus message_template_status_update, message_template_quality_update and template_category_update to follow your templates."));
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
        if (frm.doc.enable_whatsapp && frm.doc.whatsapp_business_account_id) {
            frm.add_custom_button(__("Sync WhatsApp Templates"), () => frappe.call({
                method: "thinknxg_support.thinknxg_support.doctype.support_whatsapp_template.support_whatsapp_template.sync_templates",
                freeze: true, freeze_message: __("Reading your templates from WhatsApp…"),
            }).then((r) => { frappe.show_alert({ message: r.message, indicator: "green" }); frm.reload_doc(); }),
            __("WhatsApp"));
            frm.add_custom_button(__("WhatsApp Templates"), () => frappe.set_route("List", "Support WhatsApp Template"), __("WhatsApp"));
            frm.add_custom_button(__("Marketing Opt-ins"), () => frappe.set_route("List", "Support WhatsApp Consent"), __("WhatsApp"));
        }
        frm.add_custom_button(__("Open Chat Console"), () => frappe.set_route("support-chat"));
        frm.add_custom_button(__("Preview Landing Page"), () => window.open("/thinkdesk", "_blank"));
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
