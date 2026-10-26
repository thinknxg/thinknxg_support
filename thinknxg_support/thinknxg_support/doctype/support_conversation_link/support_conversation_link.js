const BASE = "thinknxg_support.thinknxg_support.doctype.support_conversation_link.support_conversation_link";

frappe.ui.form.on("Support Conversation Link", {
    refresh(frm) {
        if (frm.is_new()) return;
        render_thread(frm);
        frm.add_custom_button(__("Reply to Customer"), () => reply(frm, 0), __("Actions"));
        frm.add_custom_button(__("Internal Note"), () => reply(frm, 1), __("Actions"));
        if (!frm.doc.helpdesk_ticket) {
            frm.add_custom_button(__("Escalate to Ticket"), () => {
                frappe.call({ method: `${BASE}.escalate`, args: { name: frm.doc.name }, freeze: true })
                    .then(() => frm.reload_doc());
            }, __("Actions"));
        }
        if (!frm.doc.customer) {
            frm.add_custom_button(__("Link to Customer"), () => {
                frappe.prompt([
                    { fieldname: "customer", fieldtype: "Link", options: "Customer", label: __("Customer"), reqd: 1 },
                    { fieldname: "contact", fieldtype: "Link", options: "Contact", label: __("Contact") },
                ], (v) => frappe.call({ method: `${BASE}.link_customer`, args: { name: frm.doc.name, ...v } })
                    .then(() => frm.reload_doc()), __("Link to Customer"));
            }, __("Actions"));
        }
        frm.add_custom_button(__("Open in Chat Console"), () =>
            frappe.set_route("support-chat", { conversation: frm.doc.name }));
    },
});

function reply(frm, internal) {
    const d = new frappe.ui.Dialog({
        title: internal ? __("Internal Note (never shown to customer)") : __("Reply to Customer"),
        fields: [{ fieldname: "content", fieldtype: "Text Editor", reqd: 1 }],
        primary_action_label: __("Send"),
        primary_action(values) {
            frappe.call({ method: `${BASE}.agent_reply`, args: { name: frm.doc.name, content: values.content, internal } })
                .then(() => { d.hide(); frm.reload_doc(); });
        },
    });
    d.show();
}

function render_thread(frm) {
    frappe.call({ method: `${BASE}.get_thread`, args: { name: frm.doc.name } }).then((r) => {
        const esc = frappe.utils.escape_html;
        const html = (r.message || []).map((m) => `
            <div style="margin:8px 0;padding:10px 12px;border-radius:8px;
                background:${m.is_internal ? "var(--yellow-50,#fffbeb)" : m.direction === "Inbound" ? "var(--gray-100)" : "var(--blue-50,#eff6ff)"}">
                <div class="text-muted small">${esc(m.sender_name || m.sender || "")} · ${esc(m.direction)}${m.is_internal ? " · " + __("Internal") : ""} · ${frappe.datetime.comment_when(m.creation)}</div>
                <div>${m.content || ""}</div>
                ${m.attachment ? `<a href="${esc(m.attachment)}" target="_blank">${__("Attachment")}</a>` : ""}
            </div>`).join("") || `<p class="text-muted">${__("No messages yet")}</p>`;
        frm.get_field("messages_html").$wrapper.html(html);
    });
}
