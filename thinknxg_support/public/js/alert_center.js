// thinkNXG Support alert centre: pop-ups and sounds for new chats, chat and conversation messages, new and assigned
// tickets, escalations and customer feedback, on every desk page. Repeating alerts keep sounding until the agent
// acknowledges them or someone picks the work up.
//
// Sound rules that matter:
//  * A browser plays sound in a tab only after a click or key press in THAT tab. Each tab unlocks itself on the
//    first interaction, and a "Turn on alert sounds" button shows until then.
//  * Only one tab rings (the "ringer"), so several open tabs do not ring together. Only a tab whose sound is
//    unlocked can be the ringer, and the tab you are working in takes over.
//  * Repeats are queued on the audio clock, which keeps time when the browser slows down background tabs.
//  * If live updates (socket.io) are not connected, stored alerts still arrive by checking every 15 seconds.
(function () {
	if (window.thinknxgAlerts) return;
	const API = "thinknxg_support.integrations.alerts.";
	const META = {
		"New Chat": { icon: "💬", color: "#0f766e" }, "Chat Message": { icon: "✉️", color: "#0369a1" },
		"New Ticket": { icon: "🎫", color: "#7c3aed" }, "Ticket Assigned": { icon: "📌", color: "#9333ea" },
		"Conversation Message": { icon: "🗨️", color: "#2563eb" }, Escalation: { icon: "🚨", color: "#b91c1c" },
		"Negative Feedback": { icon: "👎", color: "#c2410c" }, "Positive Feedback": { icon: "⭐", color: "#ca8a04" },
	};
	const TAB = Math.random().toString(36).slice(2);
	const LKEY = "thinknxg-alert-ringer";
	let cfg = null;
	const active = new Map(); // id -> { p, el, bus, timer, played }
	let ctx = null;
	let audioReady = false;
	let ringer = false;

	// ---------------------------------------------------------------- audio unlock
	function audio() {
		if (!ctx) {
			const AC = window.AudioContext || window.webkitAudioContext;
			if (!AC) return null;
			ctx = new AC();
			ctx.onstatechange = () => { audioReady = ctx.state === "running"; if (audioReady) hideUnlock(); };
		}
		return ctx;
	}
	function unlock() {
		const c = audio();
		if (!c) return Promise.resolve(false);
		// a silent sound started inside the click is what some browsers (Safari) need to unlock audio
		try {
			const b = c.createBuffer(1, 1, 22050), s = c.createBufferSource();
			s.buffer = b; s.connect(c.destination); s.start(0);
		} catch (e) { /* ignore */ }
		return c.resume().then(() => {
			audioReady = c.state === "running";
			if (audioReady) { hideUnlock(); tick(); }
			return audioReady;
		}).catch(() => false);
	}
	["pointerdown", "keydown", "touchstart"].forEach((ev) =>
		window.addEventListener(ev, () => { if (!audioReady) unlock(); }, { passive: true, capture: true }));

	let unlockEl = null;
	function showUnlock() {
		if (unlockEl || audioReady || !cfg || !cfg.enabled || (cfg.prefs && cfg.prefs.mute_all)) return;
		unlockEl = document.createElement("button");
		unlockEl.type = "button";
		unlockEl.className = "btn btn-warning btn-sm";
		unlockEl.style.cssText = "position:fixed;z-index:1060;inset-block-end:16px;inset-inline-start:16px;box-shadow:0 6px 20px rgba(0,0,0,.2)";
		unlockEl.textContent = "🔇 " + __("Turn on support alert sounds");
		unlockEl.title = __("Browsers only play sound after you click on the page once");
		unlockEl.onclick = () => unlock().then((ok) => ok && frappe.show_alert({ message: __("Alert sounds are on"), indicator: "green" }, 3));
		document.body.appendChild(unlockEl);
	}
	function hideUnlock() { if (unlockEl) { unlockEl.remove(); unlockEl = null; } }

	// ---------------------------------------------------------------- one ringing tab
	function store(fn) { try { return fn(window.localStorage); } catch (e) { return null; } }
	function claimRinger() {
		if (!audioReady) { if (ringer) loseRinger(); return false; }
		const now = Date.now();
		const cur = store((s) => JSON.parse(s.getItem(LKEY) || "null"));
		const focused = document.visibilityState === "visible" && document.hasFocus();
		if (!cur || cur.id === TAB || now - cur.t > 45000 || focused) {
			store((s) => s.setItem(LKEY, JSON.stringify({ id: TAB, t: now })));
			if (!ringer) { ringer = true; tick(); }
			return true;
		}
		if (ringer) loseRinger();
		return false;
	}
	function loseRinger() { ringer = false; active.forEach(stopSound); }
	window.addEventListener("pagehide", () => store((s) => {
		const cur = JSON.parse(s.getItem(LKEY) || "null");
		if (cur && cur.id === TAB) s.removeItem(LKEY);
	}));
	window.addEventListener("focus", claimRinger);
	window.addEventListener("storage", (e) => { if (e.key === LKEY && ringer) claimRinger(); });
	const bc = "BroadcastChannel" in window ? new BroadcastChannel("thinknxg-alerts") : null;
	if (bc) bc.onmessage = (e) => (e.data && e.data.ack ? e.data.ack.forEach((id) => remove(id)) : null);

	// ---------------------------------------------------------------- sounds
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
	// Each sound is distinct so agents know the activity without looking.
	const SOUNDS = {
		Chime: (c, d, t, v) => { tone(c, d, t, 784, 0.35, v * 0.6); tone(c, d, t + 0.18, 1175, 0.5, v * 0.55); },
		Bell: (c, d, t, v) => { [1, 2.76, 5.4].forEach((m, i) => tone(c, d, t, 660 * m, 1.1 - i * 0.3, v * (0.6 / (i + 1)))); },
		Ping: (c, d, t, v) => { tone(c, d, t, 1568, 0.25, v * 0.55); },
		Pop: (c, d, t, v) => { tone(c, d, t, 420, 0.12, v * 0.7, "triangle", 900); },
		Ring: (c, d, t, v) => { for (let k = 0; k < 2; k++) for (let i = 0; i < 8; i++) tone(c, d, t + k * 0.6 + i * 0.06, i % 2 ? 1320 : 1100, 0.055, v * 0.4, "square"); },
		"Double Beep": (c, d, t, v) => { tone(c, d, t, 988, 0.12, v * 0.5, "square"); tone(c, d, t + 0.18, 988, 0.12, v * 0.5, "square"); },
		Knock: (c, d, t, v) => { [0, 0.16, 0.32].forEach((x) => tone(c, d, t + x, 180, 0.09, v, "triangle", 90)); },
		Siren: (c, d, t, v) => { for (let i = 0; i < 3; i++) { tone(c, d, t + i * 0.5, 620, 0.25, v * 0.55, "sawtooth", 1240); tone(c, d, t + i * 0.5 + 0.25, 1240, 0.25, v * 0.55, "sawtooth", 620); } },
		Alarm: (c, d, t, v) => { for (let i = 0; i < 6; i++) tone(c, d, t + i * 0.2, i % 2 ? 1046 : 784, 0.16, v * 0.55, "square"); },
	};

	function eff(kind, once) {
		const r = (cfg && cfg.rules && cfg.rules[kind]) || { enabled: 1, popup: 1, sound: "Chime", volume: 80 };
		const pr = (cfg && cfg.prefs) || {};
		const it = (pr.items && pr.items[kind]) || {};
		const own = it.sound && it.sound !== "Team Default";
		const sound = pr.mute_all ? "None" : (own ? it.sound : r.sound);
		const popup = it.popup === "Show" ? 1 : it.popup === "Hide" ? 0 : r.popup;
		const repeat = once ? 0 : it.repeat === "Until acknowledged" ? 1 : it.repeat === "Once" ? 0 : r.repeat_until_ack;
		const vol = Math.max(0, Math.min(1, ((r.volume ?? 80) / 100) * ((pr.volume ?? 80) / 100)));
		return { sound, popup, repeat, every: Math.max(5, r.repeat_seconds || 15), max: r.max_repeats || 0, vol,
			custom: own ? null : r.custom_sound, desktop: r.desktop_notification && pr.desktop_notifications !== 0 };
	}

	function schedule(a) {
		const e = eff(a.p.kind, a.p.once);
		if (!e.sound || e.sound === "None" || !e.vol) { a.played = true; return; }
		const times = e.repeat ? (e.max || Math.ceil(300 / e.every)) : 1;
		if (e.custom) {
			let n = 0;
			const once = () => {
				if (!active.has(a.p.id) || !ringer || n >= times) return;
				const el = new Audio(e.custom); el.volume = e.vol; el.play().catch(() => {}); n++;
				if (n < times) a.timer = setTimeout(once, e.every * 1000);
			};
			once(); a.played = true;
			return;
		}
		const c = audio();
		if (!c || c.state !== "running") return;
		a.bus = c.createGain();
		a.bus.connect(c.destination);
		const fn = SOUNDS[e.sound] || SOUNDS.Chime;
		for (let i = 0; i < times; i++) fn(c, a.bus, c.currentTime + 0.05 + i * e.every, e.vol);
		a.played = true;
		if (e.repeat && !e.max) {
			a.timer = setTimeout(() => { if (active.has(a.p.id) && ringer) { stopSound(a); schedule(a); } }, (times * e.every - 5) * 1000);
		}
	}
	function stopSound(a) {
		if (a.bus) { try { a.bus.disconnect(); } catch (e) { /* gone */ } a.bus = null; }
		if (a.timer) { clearTimeout(a.timer); a.timer = null; }
	}

	// The ringer plays what is due: new alerts once, repeating alerts again after a takeover.
	function tick() {
		if (!claimRinger()) return;
		active.forEach((a) => {
			if (a.bus || a.timer) return;
			const e = eff(a.p.kind, a.p.once);
			if (!a.played || (e.repeat && a.p.stored)) schedule(a);
		});
	}
	setInterval(tick, 3000);

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
	document.addEventListener("visibilitychange", () => { title(); if (!document.hidden) claimRinger(); });

	function show(p) {
		if (!p || !p.id || active.has(p.id) || !cfg || !cfg.enabled) return;
		const e = eff(p.kind, p.once);
		const r = cfg.rules[p.kind];
		if (r && !r.enabled) return;
		const a = { p, played: !!(p.replay && !e.repeat) };
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
			if (!p.stored) setTimeout(() => remove(p.id), 15000);
		}
		if (!audioReady) showUnlock();
		if (claimRinger()) {
			if (!a.played) schedule(a);
			if (document.hidden && e.desktop && "Notification" in window && Notification.permission === "granted") {
				try {
					a.note = new Notification(`${(META[p.kind] || {}).icon || "🔔"} ${p.title}`,
						{ body: [p.body, ...(p.lines || [])].filter(Boolean).join("\n").slice(0, 300), tag: p.group_key || p.id,
							requireInteraction: !!(p.stored && e.repeat), silent: !!audioReady });
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

	// Stored alerts also arrive by checking every 15 s, so alerts are not lost when live updates are down;
	// alerts acknowledged or picked up elsewhere disappear the same way.
	function poll() {
		return frappe.call({ method: API + "my_alerts", type: "GET", quiet: true }).then((r) => {
			const rows = r.message || [];
			const ids = new Set(rows.map((x) => x.id));
			active.forEach((a, id) => { if (a.p.stored && !ids.has(id)) remove(id); });
			rows.slice().reverse().forEach((x) => show({ ...x, replay: first }));
			first = false;
		}).catch(() => {});
	}
	let first = true;

	function openPrefs() {
		frappe.call({ method: API + "open_my_preferences", type: "POST" })
			.then((r) => r.message && frappe.set_route("Form", "Support Alert Preference", r.message));
	}

	function loadConfig() {
		return frappe.call({ method: API + "config", type: "GET", quiet: true }).then((r) => { cfg = r.message || { enabled: false }; });
	}

	function test(kind, prefDoc) {
		const r = (cfg && cfg.rules && cfg.rules[kind]) || {};
		const it = ((prefDoc && prefDoc.items) || []).find((i) => i.kind === kind) || {};
		const own = it.sound && it.sound !== "Team Default";
		const sound = own ? it.sound : r.sound || "Chime";
		const vol = ((r.volume ?? 80) / 100) * (((prefDoc && prefDoc.volume) ?? 80) / 100);
		if (sound === "None" || !vol) { frappe.show_alert(__("{0}: no sound", [__(kind)])); return; }
		unlock().then(() => {
			frappe.show_alert({ message: `${(META[kind] || {}).icon || ""} ${__(kind)}: ${__(sound)}`, indicator: "blue" }, 2);
			if (r.custom_sound && !own) { const el = new Audio(r.custom_sound); el.volume = vol; el.play(); return; }
			const c = audio();
			if (c && c.state === "running") (SOUNDS[sound] || SOUNDS.Chime)(c, c.destination, c.currentTime + 0.05, vol);
		});
	}
	function testAll(prefDoc) {
		let delay = 0;
		Object.keys(META).forEach((k) => { setTimeout(() => test(k, prefDoc), delay); delay += 1900; });
	}

	// "Check alerts": what stands between this browser and a sound, plus a real test alert from the server.
	function diagnose() {
		unlock().then(() => frappe.call({ method: API + "diagnose", type: "GET" })).then((r) => {
			const d = r.message || {};
			const sock = frappe.realtime && frappe.realtime.socket;
			const rows = [
				[__("You get support alerts"), d.is_agent, d.is_agent ? __("Yes") : __("No: give this user one of these roles: {0}", [(d.agent_roles || []).join(", ")])],
				[__("Alerts switched on for the team"), (d.enabled_kinds || []).length > 0, (d.enabled_kinds || []).join(", ") || __("All activities are off in Support Alert Settings")],
				[__("All sounds muted by you"), !(cfg && cfg.prefs && cfg.prefs.mute_all), cfg && cfg.prefs && cfg.prefs.mute_all ? __("Yes: untick Mute All Sounds") : __("No")],
				[__("Live updates connected"), !!(sock && sock.connected), sock && sock.connected ? __("Yes") : __("No: alerts still arrive within 15 seconds; ask your administrator to check the realtime (socket.io) service")],
				[__("Sound allowed in this tab"), audioReady, audioReady ? __("Yes") : __("No: click anywhere on the page")],
				[__("This tab plays the sounds"), ringer, ringer ? __("Yes") : __("Another open tab does; click into this tab to move it here")],
				[__("System notifications"), "Notification" in window && Notification.permission === "granted",
					"Notification" in window ? __(Notification.permission) : __("Not supported")],
			];
			const html = `<table class="table table-bordered table-sm">${rows.map(([k, ok, v]) =>
				`<tr><td>${ok ? "✅" : "⚠️"} ${frappe.utils.escape_html(k)}</td><td>${frappe.utils.escape_html(String(v))}</td></tr>`).join("")}</table>`;
			const dlg = new frappe.ui.Dialog({
				title: __("Check support alerts"),
				fields: [{ fieldtype: "HTML", fieldname: "t", options: html },
					{ fieldtype: "Select", fieldname: "kind", label: __("Send me a test alert"), options: Object.keys(META), default: "New Chat" }],
				primary_action_label: __("Send test alert"),
				primary_action: (v) => frappe.call({ method: API + "send_test", args: { kind: v.kind }, type: "POST" })
					.then((x) => frappe.show_alert({ message: x.message, indicator: "blue" }, 6)),
			});
			dlg.show();
		});
	}

	function start() {
		if (!frappe.session || frappe.session.user === "Guest") return;
		loadConfig().then(() => {
			if (!cfg.enabled) return;
			if (frappe.realtime && frappe.realtime.on) {
				frappe.realtime.on("thinknxg_support_alert", show);
				frappe.realtime.on("thinknxg_support_alert_clear", onClear);
				frappe.realtime.on("thinknxg_support_alert_config", loadConfig);
			}
			poll();
			setInterval(poll, 15000);
			setTimeout(showUnlock, 2500);
		}).catch(() => {});
	}

	window.thinknxgAlerts = { test, testAll, diagnose, reload: loadConfig, open: openPrefs, unlock, sounds: Object.keys(SOUNDS) };
	if (document.readyState === "complete") setTimeout(start, 1000);
	else window.addEventListener("load", () => setTimeout(start, 1000));
})();
