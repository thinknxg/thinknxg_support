frappe.ui.form.on("Support Agent App Settings", {
    refresh(frm) {
        frm.add_custom_button(frm.doc.oauth_client ? __("Update OAuth Client") : __("Create OAuth Client"), () =>
            frappe.call({ method: "thinknxg_support.thinknxg_support.doctype.support_agent_app_settings.support_agent_app_settings.create_oauth_client" })
                .then((r) => { frappe.msgprint(r.message.message); frm.reload_doc(); }));
        frm.set_intro(__("Agents sign in to the apps with their own staff account in the browser. Site address for the apps: {0}", [`<b>${frappe.utils.escape_html(window.location.origin)}</b>`]));
    },
});
