frappe.ui.form.on("Support Alert Preference", {
    refresh(frm) {
        const A = window.thinknxgAlerts;
        if (A) {
            frm.add_custom_button(__("Check Alerts"), () => A.diagnose());
            frm.add_custom_button(__("Test All Sounds"), () => A.testAll(frm.doc));
            (frm.doc.items || []).forEach((row) =>
                frm.add_custom_button(__(row.kind), () => A.test(row.kind, frm.doc), __("Test Sound")));
        }
        if ("Notification" in window && Notification.permission !== "granted") {
            frm.add_custom_button(__("Allow System Notifications"), () =>
                Notification.requestPermission().then((p) => frappe.show_alert(p === "granted"
                    ? { message: __("System notifications allowed"), indicator: "green" }
                    : { message: __("The browser blocked notifications. Allow them in the site settings."), indicator: "orange" })));
        }
    },
    after_save() { window.thinknxgAlerts && window.thinknxgAlerts.reload(); },
});
