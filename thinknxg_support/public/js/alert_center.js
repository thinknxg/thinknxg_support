// thinkNXG Support alert centre: pop-ups and sounds for new chats, chat and conversation messages, new and assigned
// tickets, and escalations, on every desk page. Sounds repeat until the agent acknowledges or someone picks the work up.
// One browser tab (the "leader") plays sounds and system notifications so several open tabs do not ring at once.
(function () {
    if (window.thinknxgAlerts) return;
    const API = "thinknxg_support.integrations.alerts.";
    const META = {
        "New Chat": { icon: "💬", color: "#0f766e" }, "Chat Message": { icon: "✉️", color: "#0369a1" },
        "New Ticket": { icon: "🎫", color: "#7c3aed" }, "Ticket Assigned": { icon: "📌", color: "#9333ea" },
        "Conversation Message": { icon: "🗨️", color: "#2563eb" }, Escalation: { icon: "🚨", color: "#b91c1c" },
    };
    const TAB = Math.random().toString(36).slice(2);
    const LKEY = "thinknxg-alert-leader";
    let cfg = null;
    const active = new Map(); // id -> { p, el, bus, timer }
    let ctx = null;

    // ---------------------------------------------------------------- leader tab
    function store(fn) { try { return fn(window.localStorage); } catch (e) { return null; } }
    function isLeader() {
        const now = Date.now();
        const cur = store((s) => JSON.parse(s.getItem(LKEY) || "null"));
        if (!cur || cur.id === TAB || now - cur.t > 75000) {
            store((s) => s.setItem(LKEY, JSON.stringify({ id: TAB, t: now })));
            return true;
        }
        return false;
    }
    window.addEventListener("pagehide", () => store((s) => {
        const cur = JSON.parse(s.getItem(LKEY) || "null");
        if (cur && cur.id === TAB) s.removeItem(LKEY);
    }));
    const bc = "BroadcastChannel" in window ? new BroadcastChannel("thinknxg-alerts") : null;
    if (bc) bc.onmessage = (e) => (e.data && e.data.ack ? e.data.ack.forEach((id) => remove(id)) : null);

    // ---------------------------------------------------------------- sound
    function audio() {
        if (!ctx) {
            const AC = window.AudioContext || window.webkitAudioContext;
            if (!AC) return null;
            ctx = new AC();
        }
        return ctx;
    }
    function tone(c, dest, t, f, dur, vol, type, f2) {
        const o = c.createOscillator(), g = c.createGain();
        o.type = type || "sine";
        o.frequency.setValueAtTime(f, t);
        if (f2) o.frequency.linearRampToValueAtTime(f2, t + dur);
        g.gain.setValueAtTime(0.0001, t);
        g.gain.exponentialRampToValueAtTime(Math.max(0.0002, vol), t + 0.015);
        g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
        o.connect(g); g.connect(dest);
        o.start(t); o.stop(t + dur + 0.02);
    }
    // Each sound is distinct so agents know the activity without looking. Returns its length in seconds.
    const SOUNDS = {
        Chime: (c, d, t, v) => { tone(c, d, t, 784, 0.35, v * 0.5); tone(c, d, t + 0.18, 1175, 0.5, v * 0.45); return 0.7; },
        Bell: (c, d, t, v) => { [1, 2.76, 5.4].forEach((m, i) => tone(c, d, t, 660 * m, 1.1 - i * 0.3, v * (0.5 / (i + 1)))); return 1.1; },
        Ping: (c, d, t, v) => { tone(c, d, t, 1568, 0.25, v * 0.45); return 0.25; },
        Pop: (c, d, t, v) => { tone(c, d, t, 420, 0.12, v * 0.6, "triangle", 900); return 0.15; },
        Ring: (c, d, t, v) => { for (let i = 0; i < 8; i++) tone(c, d, t + i * 0.06, i % 2 ? 1320 : 1100, 0.055, v * 0.35, "square"); for (let i = 0; i < 8; i++) tone(c, d, t + 0.6 + i * 0.06, i % 2 ? 1320 : 1100, 0.055, v * 0.35, "square"); return 1.1; },
        "Double Beep": (c, d, t, v) => { tone(c, d, t, 988, 0.12, v * 0.45, "square"); tone(c, d, t + 0.18, 988, 0.12, v * 0.45, "square"); return 0.32; },
        Knock: (c, d, t, v) => { [0, 0.16, 0.32].forEach((x) => tone(c, d, t + x, 180, 0.09, v * 0.9, "triangle", 90)); return 0.45; },
        Siren: (c, d, t, v) => { for (let i = 0; i < 3; i++) { tone(c, d, t + i * 0.5, 620, 0.25, v * 0.5, "sawtooth", 1240); tone(c, d, t + i * 0.5 + 0.25, 1240, 0.25, v * 0.5, "sawtooth", 620); } return 1.5; },
        Alarm: (c, d, t, v) => { for (let i = 0; i < 6; i++) tone(c, d, t + i * 0.2, i % 2 ? 1046 : 784, 0.16, v * 0.5, "square"); return 1.2; },
    };

    function eff(kind) {
        const r = (cfg && cfg.rules && cfg.rules[kind]) || { enabled: 1, popup: 1, sound: "Chime", volume: 80 };
        const pr = (cfg && cfg.prefs) || {};
        const it = (pr.items && pr.items[kind]) || {};
        const sound = pr.mute_all ? "None" : (it.sound && it.sound !== "Team Default" ? it.sound : r.sound);
        const popup = it.popup === "Show" ? 1 : it.popup === "Hide" ? 0 : r.popup;
        const repeat = it.repeat === "Until acknowledged" ? 1 : it.repeat === "Once" ? 0 : r.repeat_until_ack;
        const vol = Math.max(0, Math.min(1, ((r.volume ?? 80) / 100) * ((pr.volume ?? 80) / 100)));
        return { sound, popup, repeat, every: Math.max(5, r.repeat_seconds || 15), max: r.max_repeats || 0, vol,
            custom: it.sound && it.sound !== "Team Default" ? null : r.custom_sound,
            desktop: r.desktop_notification && pr.desktop_notifications !== 0 };
    }

    // Repeats are scheduled on the audio clock, which keeps time even when the browser slows background tabs.
    function schedule(a) {
        const e = eff(a.p.kind);
        if (!e.sound || e.sound === "None" || !e.vol) return;
        const times = e.repeat ? (e.max || Math.ceil(300 / e.every)) : 1;
        if (e.custom) {
            let n = 0;
            const playOnce = () => {
                if (!active.has(a.p.id) || n >= times) return;
                const el = new Audio(e.custom); el.volume = e.vol; el.play().catch(() => needUnlock()); n++;
                if (n < times) a.timer = setTimeout(playOnce, e.every * 1000);
            };
            playOnce();
            return;
        }
        const c = audio();
        if (!c) return;
        if (c.state === "suspended") {
            c.resume().catch(() => {});
            if (c.state === "suspended") { needUnlock(); a.pending = true; return; }
        }
        a.pending = false;
        a.bus = c.createGain();
        a.bus.connect(c.destination);
        const fn = SOUNDS[e.sound] || SOUNDS.Chime;
        for (let i = 0; i < times; i++) fn(c, a.bus, c.currentTime + 0.05 + i * e.every, e.vol);
        if (e.repeat && !e.max) {
            // keep ringing past the scheduled window while the alert is still open
            a.timer = setTimeout(() => { if (active.has(a.p.id)) { stopSound(a); schedule(a); } }, (times * e.every - 5) * 1000);
        }
    }
    function stopSound(a) {
        if (a.bus) { try { a.bus.disconnect(); } catch (e) { /* already gone */ } a.bus = null; }
        if (a.timer) { clearTimeout(a.timer); a.timer = null; }
    }

    let unlockEl = null;
    function needUnlock() {
        if (unlockEl) return;
        unlockEl = document.createElement("button");
        unlockEl.type = "button";
        unlockEl.className = "btn btn-warning btn-sm";
        unlockEl.style.cssText = "position:fixed;z-index:1060;inset-block-end:16px;inset-inline-start:16px;box-shadow:0 6px 20px rgba(0,0,0,.2)";
        unlockEl.textContent = "🔇 " + __("Click to turn on support alert sounds");
        unlockEl.onclick = unlock;
        document.body.appendChild(unlockEl);
    }
    function unlock() {
        const c = audio();
        if (c) c.resume().then(() => {
            if (unlockEl) { unlockEl.remove(); unlockEl = null; }
            if (isLeader()) active.forEach((a) => { if (a.pending) schedule(a); });
        }).catch(() => {});
    }
    ["pointerdown", "keydown"].forEach((ev) => window.addEventListener(ev, () => { if (ctx && ctx.state === "suspended") unlock(); }, { passive: true }));

    // ---------------------------------------------------------------- cards
    function stack() {
        let el = document.getElementById("tx-alert-stack");
        if (!el) {
            el = document.createElement("div");
            el.id = "tx-alert-stack";
            el.setAttribute("role", "region");
            el.setAttribute("aria-label", __("Support alerts"));
            el.style.cssText = "position:fixed;z-index:1050;inset-block-end:16px;inset-inline-end:16px;display:flex;flex-direction:column;" +
                "gap:8px;width:min(380px,calc(100vw - 32px));max-height:85vh;overflow:auto";
            document.body.appendChild(el);
        }
        return el;
    }
    function go(p) {
        if (!p.route) return;
        if (p.route.startsWith("/")) { window.open(p.route, "_blank", "noopener"); return; }
        const [path, qs] = p.route.split("?");
        if (qs) frappe.route_options = Object.fromEntries(new URLSearchParams(qs));
        frappe.set_route(path.split("/"));
    }
    function ack(id) {
        const a = active.get(id);
        if (a && a.p.stored) frappe.call({ method: API + "acknowledge", args: { ids: [id] }, type: "POST" }).catch(() => {});
        remove(id);
        if (bc) bc.postMessage({ ack: [id] });
    }
    function remove(id) {
        const a = active.get(id);
        if (!a) return;
        stopSound(a);
        if (a.el) a.el.remove();
        if (a.note) try { a.note.close(); } catch (e) { /* closed */ }
        active.delete(id);
        title();
    }
    function title() {
        const n = [...active.values()].filter((a) => a.p.stored).length;
        const base = document.title.replace(/^\(\d+\) 🔔 /, "");
        document.title = n && document.hidden ? `(${n}) 🔔 ${base}` : base;
    }
    document.addEventListener("visibilitychange", title);

    function show(p) {
        if (!p || !p.id || active.has(p.id) || !cfg || !cfg.enabled) return;
        const e = eff(p.kind);
        const r = cfg.rules[p.kind];
        if (r && !r.enabled) return;
        const a = { p };
        active.set(p.id, a);
        if (e.popup) {
            const m = META[p.kind] || { icon: "🔔", color: "#475569" };
            const esc = frappe.utils.escape_html;
            const el = document.createElement("div");
            el.setAttribute("role", p.kind === "Escalation" ? "alert" : "status");
            el.style.cssText = "background:var(--card-bg,#fff);color:var(--text-color);border:1px solid var(--border-color);" +
                `border-inline-start:5px solid ${m.color};border-radius:10px;padding:10px 12px;box-shadow:0 10px 30px rgba(0,0,0,.16);font-size:13px` +
                (p.kind === "Escalation" ? ";outline:2px solid " + m.color + "33" : "");
            const lines = (p.lines || []).filter(Boolean).map((l) => `<div class="text-muted">${esc(l)}</div>`).join("");
            el.innerHTML = `
                <div style="display:flex;gap:8px;align-items:flex-start;justify-content:space-between">
                    <div><span aria-hidden="true">${m.icon}</span> <small style="color:${m.color};font-weight:600">${esc(__(p.kind))}</small>
                    ${p.priority ? `<small class="text-muted"> · ${esc(__(p.priority))}</small>` : ""}</div>
                    <div style="display:flex;gap:2px">
                        <button type="button" class="btn btn-xs btn-link" data-pref title="${esc(__("My alert preferences"))}" aria-label="${esc(__("My alert preferences"))}">⚙</button>
                        <button type="button" class="btn btn-xs btn-link" data-x title="${esc(__("Dismiss"))}" aria-label="${esc(__("Dismiss"))}">✕</button>
                    </div>
                </div>
                <div style="font-weight:600;margin:4px 0 2px">${esc(p.title || "")}</div>
                ${p.body ? `<div style="max-height:3.2em;overflow:hidden">${esc(p.body)}</div>` : ""}${lines}
                <div style="display:flex;gap:6px;margin-top:8px">
                    ${p.route ? `<button type="button" class="btn btn-primary btn-xs" data-open>${esc(__("Open"))}</button>` : ""}
                    ${p.stored ? `<button type="button" class="btn btn-default btn-xs" data-ack>${esc(__("Acknowledge"))}</button>` : ""}
                </div>`;
            el.querySelector("[data-x]").onclick = () => (p.stored ? ack(p.id) : remove(p.id));
            el.querySelector("[data-pref]").onclick = openPrefs;
            const ackBtn = el.querySelector("[data-ack]");
            if (ackBtn) ackBtn.onclick = () => ack(p.id);
            const openBtn = el.querySelector("[data-open]");
            if (openBtn) openBtn.onclick = () => { ack(p.id); go(p); };
            stack().prepend(el);
            a.el = el;
            if (!p.stored) setTimeout(() => remove(p.id), 15000); // message pop-ups fade on their own
        }
        if (isLeader() && !(p.replay && !e.repeat)) {
            schedule(a);
            if (document.hidden && e.desktop && "Notification" in window && Notification.permission === "granted") {
                try {
                    a.note = new Notification(`${(META[p.kind] || {}).icon || "🔔"} ${p.title}`,
                        { body: [p.body, ...(p.lines || [])].filter(Boolean).join("\n").slice(0, 300), tag: p.group_key || p.id,
                            requireInteraction: !!(p.stored && e.repeat), silent: true });
                    a.note.onclick = () => { window.focus(); ack(p.id); go(p); };
                } catch (err) { /* notifications unavailable */ }
            }
        }
        title();
    }

    function onClear(d) {
        (d.ids || []).forEach(remove);
        if (d.group) {
            active.forEach((a, id) => {
                const g = a.p.group_key || "";
                if (d.prefix ? g.startsWith(d.group) : g === d.group) remove(id);
            });
        }
    }

    function openPrefs() {
        frappe.call({ method: API + "open_my_preferences", type: "POST" })
            .then((r) => r.message && frappe.set_route("Form", "Support Alert Preference", r.message));
    }

    function loadConfig() {
        return frappe.call({ method: API + "config", type: "GET" }).then((r) => { cfg = r.message || { enabled: false }; });
    }

    function test(kind, prefDoc) {
        const r = (cfg && cfg.rules && cfg.rules[kind]) || {};
        const it = ((prefDoc && prefDoc.items) || []).find((i) => i.kind === kind) || {};
        const sound = it.sound && it.sound !== "Team Default" ? it.sound : r.sound || "Chime";
        const vol = ((r.volume ?? 80) / 100) * (((prefDoc && prefDoc.volume) ?? 80) / 100);
        if (sound === "None") { frappe.show_alert(__("{0}: no sound", [__(kind)])); return 0; }
        if (r.custom_sound && (!it.sound || it.sound === "Team Default")) { const el = new Audio(r.custom_sound); el.volume = vol; el.play(); return 2; }
        const c = audio(); if (!c) return 0;
        c.resume();
        frappe.show_alert({ message: `${(META[kind] || {}).icon || ""} ${__(kind)}: ${__(sound)}`, indicator: "blue" }, 2);
        return (SOUNDS[sound] || SOUNDS.Chime)(c, c.destination, c.currentTime + 0.05, vol);
    }
    function testAll(prefDoc) {
        let delay = 0;
        Object.keys(META).forEach((k) => { setTimeout(() => test(k, prefDoc), delay); delay += 1900; });
    }

    function start() {
        if (!frappe.session || frappe.session.user === "Guest" || !frappe.realtime) return;
        loadConfig().then(() => {
            if (!cfg.enabled) return;
            frappe.realtime.on("thinknxg_support_alert", show);
            frappe.realtime.on("thinknxg_support_alert_clear", onClear);
            frappe.realtime.on("thinknxg_support_alert_config", loadConfig);
            frappe.call({ method: API + "my_alerts", type: "GET" }).then((r) => (r.message || []).reverse().forEach(show)).catch(() => {});
            setInterval(() => { if (isLeader()) active.forEach((a) => { if (!a.bus && !a.timer && a.pending) schedule(a); }); }, 20000);
        }).catch(() => {});
    }

    window.thinknxgAlerts = { test, testAll, reload: loadConfig, open: openPrefs, sounds: Object.keys(SOUNDS) };
    if (document.readyState === "complete") setTimeout(start, 1200);
    else window.addEventListener("load", () => setTimeout(start, 1200));
})();
