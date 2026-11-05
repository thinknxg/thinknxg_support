// thinkNXG Support: pop-up alerts for escalated support queries, shown anywhere in the desk.
(function () {
    const EVENT = "thinknxg_support_escalation";
    const API = "thinknxg_support.integrations.escalations.";
    const COLORS = { Critical: "#b91c1c", High: "#c2410c", Medium: "#1d4ed8", Low: "#475569" };
    const shown = new Set();

    function stack() {
        let el = document.getElementById("tx-esc-stack");
        if (!el) {
            el = document.createElement("div");
            el.id = "tx-esc-stack";
            el.setAttribute("role", "region");
            el.setAttribute("aria-label", __("Escalation alerts"));
            el.style.cssText = "position:fixed;z-index:1050;inset-block-end:16px;inset-inline-end:16px;display:flex;" +
                "flex-direction:column;gap:10px;width:min(380px,calc(100vw - 32px));max-height:80vh;overflow:auto";
            document.body.appendChild(el);
        }
        return el;
    }

    function beep() {
        try {
            const ctx = new (window.AudioContext || window.webkitAudioContext)();
            [0, 0.18].forEach((t) => {
                const o = ctx.createOscillator(), g = ctx.createGain();
                o.frequency.value = 880; o.connect(g); g.connect(ctx.destination);
                g.gain.setValueAtTime(0.0001, ctx.currentTime + t);
                g.gain.exponentialRampToValueAtTime(0.15, ctx.currentTime + t + 0.02);
                g.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + t + 0.15);
                o.start(ctx.currentTime + t); o.stop(ctx.currentTime + t + 0.16);
            });
        } catch (e) { /* sound is optional */ }
    }

    function ack(name) { frappe.call({ method: API + "acknowledge", args: { name }, type: "POST" }).catch(() => {}); }

    function show(p) {
        const key = p.name + ":" + p.reason;
        if (shown.has(key)) return;
        shown.add(key);
        const esc = frappe.utils.escape_html;
        const card = document.createElement("div");
        card.setAttribute("role", "alert");
        card.style.cssText = "background:var(--card-bg,#fff);color:var(--text-color);border:1px solid var(--border-color);" +
            `border-inline-start:5px solid ${COLORS[p.priority] || "#475569"};border-radius:10px;padding:12px 14px;` +
            "box-shadow:0 10px 30px rgba(0,0,0,.18);font-size:13px";
        card.innerHTML = `
            <div style="display:flex;justify-content:space-between;gap:8px;align-items:flex-start">
                <div><span style="background:${COLORS[p.priority] || "#475569"};color:#fff;border-radius:4px;padding:1px 7px;font-size:11px">${esc(__(p.priority))}</span>
                <b style="margin-inline-start:6px">${esc(p.title)}</b></div>
                <button type="button" class="btn btn-xs btn-link" data-x aria-label="${esc(__("Dismiss"))}" style="padding:0 4px">✕</button>
            </div>
            <div style="margin:6px 0 2px;font-weight:600">${esc(p.subject || "")}</div>
            <div class="text-muted">${esc(p.customer)}${p.customer_details ? " · " + esc(p.customer_details) : ""}</div>
            <div class="text-muted">${esc(p.query_type)} · ${esc(p.escalation_type)}${p.level > 1 ? " · L" + p.level : ""} · ${esc(p.name)}</div>
            <div class="text-muted">${esc(__("Assigned to"))}: ${esc(p.assigned_to)} · ${esc(p.escalated_on_label || "")}</div>
            <div style="display:flex;gap:8px;margin-top:10px">
                <button type="button" class="btn btn-primary btn-xs" data-open>${esc(__("Open"))}</button>
                <button type="button" class="btn btn-default btn-xs" data-ack>${esc(__("Acknowledge"))}</button>
            </div>`;
        const close = () => card.remove();
        card.querySelector("[data-x]").onclick = close;
        card.querySelector("[data-ack]").onclick = () => { ack(p.name); close(); };
        card.querySelector("[data-open]").onclick = () => { ack(p.name); close(); frappe.set_route("Form", "Support Escalation", p.name); };
        stack().prepend(card);
        if (p.sound) beep();
        if (document.hidden) {
            const old = document.title;
            document.title = "🔔 " + __("Escalation") + " · " + old;
            document.addEventListener("visibilitychange", function back() {
                if (!document.hidden) { document.title = old; document.removeEventListener("visibilitychange", back); }
            });
        }
    }

    function start() {
        if (!frappe.realtime || !frappe.session || frappe.session.user === "Guest") return;
        frappe.realtime.on(EVENT, show);
        frappe.call({ method: API + "pending_alerts", type: "GET" }).then((r) => (r.message || []).forEach(show)).catch(() => {});
    }

    if (document.readyState === "complete") setTimeout(start, 1500);
    else window.addEventListener("load", () => setTimeout(start, 1500));
})();
