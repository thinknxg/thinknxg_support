const SA = "thinknxg_support.api.v1.analytics.";
const esc = (s) => frappe.utils.escape_html(s == null ? "" : String(s));

frappe.pages["support-analytics"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Support Analytics"), single_column: true });
	wrapper.analytics = new SupportAnalytics(page);
};
frappe.pages["support-analytics"].on_page_show = (wrapper) => wrapper.analytics && wrapper.analytics.refresh();

function dur(s) {
	if (s == null) return "—";
	s = Math.round(s);
	if (s < 60) return `${s}s`;
	if (s < 3600) return `${Math.floor(s / 60)}m ${s % 60}s`;
	if (s < 86400) return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
	return `${Math.floor(s / 86400)}d ${Math.floor((s % 86400) / 3600)}h`;
}
const pct = (v) => (v == null ? "—" : `${v}%`);
const num = (v) => (v == null ? "—" : Number(v).toLocaleString());

class SupportAnalytics {
	constructor(page) {
		this.page = page;
		this.charts = {};
		this.page.set_primary_action(__("Refresh"), () => this.refresh(true), "refresh");
		this.page.add_menu_item(__("Live Chat Performance report"), () => frappe.set_route("query-report", "Live Chat Performance"));
		this.page.add_menu_item(__("Agent CSAT report"), () => frappe.set_route("query-report", "Agent CSAT"));
		this.page.add_menu_item(__("Usage limits"), () => frappe.set_route("Form", "Support Usage Limits"));
		this.page.add_menu_item(__("Privacy requests"), () => frappe.set_route("List", "Support Privacy Request"));
		this.range = this.page.add_field({ fieldname: "range", label: __("Period"), fieldtype: "Select",
			options: [{ value: "7", label: __("Last 7 days") }, { value: "30", label: __("Last 30 days") },
				{ value: "90", label: __("Last 90 days") }, { value: "custom", label: __("Custom") }],
			default: "30", change: () => this.onRange() });
		this.from = this.page.add_field({ fieldname: "from_date", label: __("From"), fieldtype: "Date", change: () => this.schedule() });
		this.to = this.page.add_field({ fieldname: "to_date", label: __("To"), fieldtype: "Date", change: () => this.schedule() });
		this.channel = this.page.add_field({ fieldname: "channel", label: __("Channel"), fieldtype: "Select",
			options: ["", "Live Chat", "WhatsApp", "Portal"], change: () => this.schedule() });
		this.queue = this.page.add_field({ fieldname: "queue", label: __("Queue"), fieldtype: "Link", options: "Support Chat Queue", change: () => this.schedule() });
		this.$body = $(`<div class="support-analytics" style="padding: 8px 0 32px"></div>`).appendTo(this.page.main);
		this.$body.html(`
			<div class="sa-live"></div>
			<h5 class="mt-4">${__("Period")}<span class="sa-period text-muted small ml-2"></span></h5>
			<div class="sa-tiles row"></div>
			<div class="row">
				<div class="col-md-8"><div class="frappe-card p-3 mb-3"><h6>${__("Conversations per day: AI resolved, human, other")}</h6><div class="sa-chart-volume"></div></div></div>
				<div class="col-md-4"><div class="frappe-card p-3 mb-3"><h6>${__("Channels")}</h6><div class="sa-chart-channels"></div></div></div>
			</div>
			<div class="row">
				<div class="col-md-8"><div class="frappe-card p-3 mb-3"><h6>${__("Median first response (minutes)")}</h6><div class="sa-chart-first"></div></div></div>
				<div class="col-md-4"><div class="frappe-card p-3 mb-3"><h6>${__("Customer mood")}</h6><div class="sa-chart-sentiment"></div></div></div>
			</div>
			<div class="row">
				<div class="col-md-4"><div class="frappe-card p-3 mb-3"><h6>${__("Why chats went to people")}</h6><div class="sa-list-handoff"></div></div></div>
				<div class="col-md-4"><div class="frappe-card p-3 mb-3"><h6>${__("What customers ask about")}</h6><div class="sa-list-intents"></div></div></div>
				<div class="col-md-4"><div class="frappe-card p-3 mb-3"><h6>${__("Languages")}</h6><div class="sa-list-languages"></div></div></div>
			</div>
			<div class="frappe-card p-3 mb-3"><h6>${__("Agent performance")}</h6><div class="sa-agents"></div></div>
			<div class="row">
				<div class="col-md-6"><div class="frappe-card p-3 mb-3"><h6>${__("AI usage")}</h6><div class="sa-ai"></div></div></div>
				<div class="col-md-6"><div class="frappe-card p-3 mb-3"><h6>${__("Usage and limits")}</h6><div class="sa-usage"></div></div></div>
			</div>
			<div class="frappe-card p-3 mb-3"><h6>${__("WhatsApp templates")}</h6><div class="sa-templates"></div></div>
			<div class="frappe-card p-3 mb-3"><h6>${__("Security check")}</h6><div class="sa-security"></div></div>
			<p class="text-muted small">${__("AI resolved: closed without a person replying, after the assistant answered. Human: a person replied. AI resolution rate: AI resolved out of the chats the assistant answered. First response: from handoff (or from the start) to the first agent reply. Figures refresh every five minutes; the live panel every 30 seconds.")}</p>`);
		this.onRange(true);
		this.timer = setInterval(() => !document.hidden && $(this.page.main).is(":visible") && this.loadLive(), 30000);
	}

	schedule() {
		clearTimeout(this.pending);
		this.pending = setTimeout(() => this.refresh(), 250);
	}

	onRange(initial) {
		const r = this.range.get_value();
		const custom = r === "custom";
		$(this.from.wrapper).toggle(custom);
		$(this.to.wrapper).toggle(custom);
		if (!custom) {
			this.to.set_value(frappe.datetime.get_today());
			this.from.set_value(frappe.datetime.add_days(frappe.datetime.get_today(), -(parseInt(r, 10) - 1)));
		}
		this.schedule();
	}

	args() {
		return { from_date: this.from.get_value(), to_date: this.to.get_value(), channel: this.channel.get_value() || "",
			queue: this.queue.get_value() || "" };
	}

	async refresh(force) {
		if (this.busy) return;
		this.busy = true;
		try {
			if (force) await frappe.call({ method: SA + "refresh" });
			const a = this.args();
			const [o, ag] = await Promise.all([
				frappe.call({ method: SA + "overview", args: a, type: "GET" }),
				frappe.call({ method: SA + "agents", args: a, type: "GET" }),
			]);
			this.renderOverview(o.message);
			this.renderAgents(ag.message || []);
			this.loadLive();
			this.loadUsage();
			this.loadSecurity();
		} finally {
			this.busy = false;
		}
	}

	tile(label, value, note, colour) {
		return `<div class="col-6 col-md-3 mb-3"><div class="frappe-card p-3 h-100">
			<div class="text-muted small">${esc(label)}</div>
			<div style="font-size: 1.6rem; font-weight: 600; color: ${colour || "inherit"}">${esc(value)}</div>
			<div class="text-muted small">${esc(note || "")}</div></div></div>`;
	}

	renderOverview(d) {
		const t = d.totals;
		this.$body.find(".sa-period").text(`${frappe.datetime.str_to_user(d.period.from)} – ${frappe.datetime.str_to_user(d.period.to)}${d.truncated ? " · " + __("first 50,000 chats only") : ""}`);
		this.$body.find(".sa-tiles").html([
			this.tile(__("Conversations"), num(t.conversations), __("{0} closed", [num(t.closed)])),
			this.tile(__("AI resolved"), num(t.ai_resolved), __("{0} of all chats", [pct(t.automation_rate)]), "var(--green-600)"),
			this.tile(__("Human handled"), num(t.human_handled), __("{0} handoffs", [num(t.handoffs)]), "var(--blue-600)"),
			this.tile(__("AI resolution rate"), pct(t.ai_resolution_rate), __("of {0} chats the assistant answered", [num(t.ai_answered)])),
			this.tile(__("First response (median)"), dur(t.first_response_median), __("90% within {0}", [dur(t.first_response_p90)])),
			this.tile(__("Resolution time (median)"), dur(t.resolution_median), __("90% within {0}", [dur(t.resolution_p90)])),
			this.tile(__("Customer satisfaction"), t.csat_average == null ? "—" : `${t.csat_average} / 5`, __("{0} positive · {1} ratings", [pct(t.csat_positive), num(t.ratings)])),
			this.tile(__("AI tokens"), num(t.ai_tokens), __("{0} calls · {1} errors", [num(t.ai_calls), num(t.ai_errors)])),
			this.tile(__("Leads from chats"), num(t.leads), __("{0} converted", [num(t.lead_conversions)])),
			this.tile(__("Automation rule runs"), num(t.automation_runs), ""),
		].join(""));
		const labels = d.daily.map((x) => frappe.datetime.str_to_user(x.date));
		this.chart("volume", { type: "bar", height: 240, barOptions: { stacked: 1 }, colors: ["#30a46c", "#2490ef", "#b8c2cc"],
			data: { labels, datasets: [{ name: __("AI resolved"), values: d.daily.map((x) => x.ai) },
				{ name: __("Human"), values: d.daily.map((x) => x.human) }, { name: __("Other"), values: d.daily.map((x) => x.other) }] } });
		this.chart("first", { type: "line", height: 220, colors: ["#2490ef"], lineOptions: { regionFill: 1 },
			data: { labels, datasets: [{ name: __("Minutes"), values: d.daily.map((x) => x.first_response_median == null ? 0 : Math.round(x.first_response_median / 6) / 10) }] } });
		this.pie("channels", d.channels);
		this.pie("sentiment", d.sentiment);
		this.list(".sa-list-handoff", d.handoff_reasons);
		this.list(".sa-list-intents", d.intents, __("Turn on message analysis in Support AI Settings to see this."));
		this.list(".sa-list-languages", d.languages);
		const wt = d.whatsapp_templates || [];
		this.$body.find(".sa-templates").html(wt.length ? `<table class="table table-sm mb-0"><thead><tr>
			<th>${__("Template")}</th><th>${__("Category")}</th><th>${__("Status")}</th><th class="text-right">${__("Sent")}</th>
			<th class="text-right">${__("Delivered")}</th><th class="text-right">${__("Read")}</th><th class="text-right">${__("Failed")}</th><th>${__("Most common failure")}</th></tr></thead>
			<tbody>${wt.map((r) => `<tr><td>${esc(r.template_name)} <span class="text-muted">${esc(r.language || "")}</span></td><td>${esc(__(r.category || ""))}</td>
			<td>${esc(__(r.status || ""))}${r.quality ? ` · ${esc(__(r.quality))}` : ""}</td><td class="text-right">${num(r.sent + r.failed)}</td>
			<td class="text-right">${pct(r.delivery_rate)}</td><td class="text-right">${pct(r.read_rate)}</td>
			<td class="text-right">${num(r.failed)}</td><td class="small">${(r.errors || []).slice(0, 1).map((e) => esc(e.meaning || e.code) + ` (${num(e.count)})`).join("")}</td></tr>`).join("")}</tbody></table>`
			: `<p class="text-muted">${__("No WhatsApp templates were sent in this period.")}</p>`);
		this.list(".sa-ai", (d.ai_usage || []).concat((d.automation || []).map((r) => ({ label: __("Rule: {0}", [r.label]), count: r.count }))), __("No AI calls in this period."));
	}

	chart(key, opts) {
		const el = this.$body.find(`.sa-chart-${key}`)[0];
		if (!opts.data.labels.length) { $(el).html(`<p class="text-muted">${__("No data")}</p>`); return; }
		$(el).empty();
		this.charts[key] = new frappe.Chart(el, opts);
	}

	pie(key, rows) {
		const el = this.$body.find(`.sa-chart-${key}`)[0];
		if (!rows || !rows.length) { $(el).html(`<p class="text-muted">${__("No data")}</p>`); return; }
		$(el).empty();
		this.charts[key] = new frappe.Chart(el, { type: "donut", height: 220,
			data: { labels: rows.map((r) => __(r.label)), datasets: [{ values: rows.map((r) => r.count) }] } });
	}

	list(sel, rows, empty) {
		const total = (rows || []).reduce((a, r) => a + r.count, 0);
		this.$body.find(sel).html(rows && rows.length ? `<table class="table table-sm mb-0">${rows.map((r) =>
			`<tr><td>${esc(r.label)}</td><td class="text-right">${num(r.count)}</td><td class="text-right text-muted">${Math.round((100 * r.count) / total)}%</td></tr>`).join("")}</table>`
			: `<p class="text-muted">${esc(empty || __("No data"))}</p>`);
	}

	renderAgents(rows) {
		this.$body.find(".sa-agents").html(rows.length ? `<div class="table-responsive"><table class="table table-sm table-hover mb-0">
			<thead><tr><th>${__("Agent")}</th><th class="text-right">${__("Chats")}</th><th class="text-right">${__("First response")}</th>
			<th class="text-right">${__("Handling time")}</th><th class="text-right">${__("Transferred")}</th><th class="text-right">${__("CSAT")}</th>
			<th class="text-right">${__("Alert response")}</th></tr></thead><tbody>${rows.map((r) => `<tr>
			<td>${esc(r.name)}</td><td class="text-right">${num(r.chats)}</td><td class="text-right">${dur(r.first_response_median)}</td>
			<td class="text-right">${dur(r.handling_median)}</td><td class="text-right">${num(r.transferred)}</td>
			<td class="text-right">${r.csat_average == null ? "—" : `${r.csat_average} (${r.ratings})`}</td>
			<td class="text-right">${dur(r.alert_ack_median)}</td></tr>`).join("")}</tbody></table></div>`
			: `<p class="text-muted">${__("No agent handled a chat in this period.")}</p>`);
	}

	async loadLive() {
		const r = await frappe.call({ method: SA + "live", type: "GET", quiet: true });
		const d = r.message;
		if (!d) return;
		const waits = d.waiting.map((w) => `<tr class="sa-open" data-name="${esc(w.conversation)}" style="cursor:pointer">
			<td>${esc(w.name || w.subject)}${w.urgent ? ` <span class="indicator-pill red">${__("Urgent")}</span>` : ""}</td>
			<td>${esc(__(w.channel))}</td><td>${esc(w.queue || "")}</td><td class="text-right">${dur(w.waiting_seconds)}</td></tr>`).join("");
		const events = d.events.slice(0, 12).map((e) => `<tr class="sa-open" data-name="${esc(e.conversation)}" style="cursor:pointer">
			<td class="text-muted">${esc(frappe.datetime.prettyDate(e.at))}</td><td>${esc(__(e.event))}</td><td>${esc(e.subject)}</td></tr>`).join("");
		this.$body.find(".sa-live").html(`<div class="row">
			${this.tile(__("Waiting now"), num(d.waiting_count), __("longest {0}", [dur(d.longest_wait_seconds)]), d.waiting_count ? "var(--orange-600)" : null)}
			${this.tile(__("Active (15 min)"), num(d.active_count), Object.entries(d.active).map(([k, v]) => `${__(k)} ${v}`).join(" · "))}
			${this.tile(__("Visitors online"), num(d.visitors_online), __("in open guest chats"))}
			${this.tile(__("Open conversations"), num(d.open_count), __("updated {0}", [frappe.datetime.prettyDate(d.server_time)]))}
		</div><div class="row">
			<div class="col-md-6"><div class="frappe-card p-3 mb-3"><h6>${__("Waiting for an agent")}</h6>${waits ? `<table class="table table-sm mb-0">${waits}</table>` : `<p class="text-muted">${__("Nobody is waiting.")}</p>`}</div></div>
			<div class="col-md-6"><div class="frappe-card p-3 mb-3"><h6>${__("Live activity (24 hours)")}</h6>${events ? `<table class="table table-sm mb-0">${events}</table>` : `<p class="text-muted">${__("No activity.")}</p>`}</div></div>
		</div>`);
		this.$body.find(".sa-live .sa-open").on("click", (e) => frappe.set_route("support-chat", { conversation: $(e.currentTarget).data("name") }));
	}

	async loadUsage() {
		const r = await frappe.call({ method: SA + "usage", type: "GET", quiet: true });
		const rows = r.message || [];
		this.$body.find(".sa-usage").html(`<table class="table table-sm mb-0"><thead><tr><th></th><th class="text-right">${__("Used")}</th><th class="text-right">${__("Limit")}</th></tr></thead>
			${rows.map((x) => `<tr><td>${esc(x.label)}</td><td class="text-right">${num(x.used)}</td><td class="text-right">${x.limit == null ? __("None") : num(x.limit)}</td></tr>`).join("")}</table>`);
	}

	async loadSecurity() {
		const r = await frappe.call({ method: SA + "security_checks", type: "GET", quiet: true });
		this.renderSecurity(r.message || []);
	}

	renderSecurity(rows) {
		const $el = this.$body.find(".sa-security");
		$el.html(rows.map((c) => `<div class="d-flex mb-2"><span class="indicator-pill ${c.ok ? "green" : "orange"} mr-2">${c.ok ? __("OK") : __("Check")}</span>
			<div><b>${esc(c.title)}</b> <span class="text-muted">${esc(c.detail)}</span>${c.ok ? "" : `<div class="small">${esc(c.fix)}</div>`}
			${c.action && frappe.user.has_role("System Manager") ? `<button class="btn btn-xs btn-primary mt-1 sa-2fa">${__("Require two-factor for support roles")}</button>` : ""}</div></div>`).join(""));
		$el.find(".sa-2fa").on("click", () => frappe.confirm(
			__("Support agents, managers and administrators will need a sign-in code from their next sign-in. Make sure they can set up an authenticator app. Continue?"),
			() => frappe.call({ method: SA + "require_two_factor" }).then((r) => { this.renderSecurity(r.message || []); frappe.show_alert({ message: __("Two-factor is now required for support roles."), indicator: "green" }); })));
	}
}
