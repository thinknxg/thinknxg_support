frappe.ui.form.on("Support Agent App Settings", {
    refresh(frm) {
        frm.add_custom_button(frm.doc.oauth_client ? __("Update OAuth Client") : __("Create OAuth Client"), () =>
            frappe.call({ method: "thinknxg_support.thinknxg_support.doctype.support_agent_app_settings.support_agent_app_settings.create_oauth_client" })
                .then((r) => { frappe.msgprint(r.message.message); frm.reload_doc(); }));
        if (frm.doc.push_enabled) {
            frm.add_custom_button(__("Send Test Push to Me"), () =>
                frappe.call({ method: "thinknxg_support.api.staff.v1.send_test_push" }).then((r) => {
                    const m = r.message || {};
                    frappe.msgprint(m.sent ? __("Sent to {0} device(s).", [m.sent]) : __("Not sent: {0}", [m.skipped || __("no devices registered for you")]));
                }));
        }
        frm.set_intro(__("Agents sign in to the apps with their own staff account in the browser. Site address for the apps: {0}", [`<b>${frappe.utils.escape_html(window.location.origin)}</b>`]));
    },
});
