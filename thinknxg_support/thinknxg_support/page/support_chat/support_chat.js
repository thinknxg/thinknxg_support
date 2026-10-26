// thinkNXG Support - agent chat console: one inbox for portal messages, live chat and WhatsApp.
const API = "thinknxg_support.api.v1.agent.";
const CHANNEL_LABEL = { Portal: __("Portal"), "Live Chat": __("Live chat"), WhatsApp: __("WhatsApp") };

frappe.pages["support-chat"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Support Chat"), single_column: true });
	wrapper.console = new SupportChatConsole(page, wrapper);
};

frappe.pages["support-chat"].on_page_show = function (wrapper) {
	const route = frappe.get_route();
	const want = (frappe.route_options && frappe.route_options.conversation) || null;
	frappe.route_options = null;
	if (wrapper.console) wrapper.console.show(want);
};

class SupportChatConsole {
	constructor(page, wrapper) {
		this.page = page;
		this.filters = { status: "active", channel: "", mine: 0, search: "" };
		this.active = null;
		this.internal = 0;
		this.build();
		this.page.set_secondary_action(__("Settings"), () => frappe.set_route("Form", "Support Portal Settings"));
		frappe.realtime.doctype_subscribe && frappe.realtime.doctype_subscribe("Support Conversation Link");
		frappe.realtime.on("thinknxg_support_chat", (d) => this.onEvent(d));
		this.timer = setInterval(() => !document.hidden && this.refresh(true), 15000);
		this.refresh();
	}

	build() {
		const $b = $(this.page.body).addClass("tx-console");
		$b.html(`
			<style>
				.tx-console .txk { display:grid; grid-template-columns: 340px minmax(0,1fr); gap:0; height: calc(100vh - 160px);
					min-height:520px; border:1px solid var(--border-color); border-radius:var(--border-radius-lg); overflow:hidden; background:var(--card-bg); }
				.tx-console .txk-side { border-inline-end:1px solid var(--border-color); display:flex; flex-direction:column; min-height:0; }
				.tx-console .txk-filters { padding:10px; display:grid; gap:8px; border-bottom:1px solid var(--border-color); }
				.tx-console .txk-tabs { display:flex; gap:4px; flex-wrap:wrap; }
				.tx-console .txk-tabs button { border:1px solid var(--border-color); background:var(--bg-color); border-radius:999px;
					padding:2px 10px; font-size:var(--text-sm); color:var(--text-muted); }
				.tx-console .txk-tabs button.on { background:var(--primary); border-color:var(--primary); color:var(--white, #fff); }
				.tx-console .txk-list { overflow:auto; flex:1; }
				.tx-console .txk-item { display:grid; grid-template-columns:auto 1fr auto; gap:10px; padding:10px 12px; cursor:pointer;
					border-bottom:1px solid var(--border-color); align-items:start; }
				.tx-console .txk-item:hover { background:var(--bg-light-gray, var(--subtle-fg)); }
				.tx-console .txk-item.on { background:var(--control-bg); }
				.tx-console .txk-av { width:34px; height:34px; border-radius:50%; display:grid; place-items:center; font-weight:600;
					font-size:12px; color:#fff; }
				.tx-console .txk-av.Portal { background:#2563eb; } .tx-console .txk-av.Live { background:#0f766e; }
				.tx-console .txk-av.WhatsApp { background:#128c7e; }
				.tx-console .txk-name { font-weight:600; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
				.tx-console .txk-prev { color:var(--text-muted); font-size:var(--text-sm); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
				.tx-console .txk-meta { text-align:end; font-size:var(--text-xs); color:var(--text-muted); display:grid; gap:4px; justify-items:end; }
				.tx-console .txk-badge { background:var(--primary); color:#fff; border-radius:999px; min-width:20px; padding:0 6px;
					font-size:11px; font-weight:700; text-align:center; }
				.tx-console .txk-main { display:flex; flex-direction:column; min-width:0; min-height:0; }
				.tx-console .txk-head { padding:12px 16px; border-bottom:1px solid var(--border-color); display:flex; gap:12px;
					justify-content:space-between; align-items:flex-start; flex-wrap:wrap; }
				.tx-console .txk-head h4 { margin:0 0 2px; }
				.tx-console .txk-head small { color:var(--text-muted); }
				.tx-console .txk-pill { display:inline-block; border-radius:999px; padding:1px 8px; font-size:11px; font-weight:600;
					background:var(--bg-color); border:1px solid var(--border-color); margin-inline-end:4px; }
				.tx-console .txk-pill.ok { color:var(--green-600, #15803d); } .tx-console .txk-pill.warn { color:var(--orange-600, #c2410c); }
				.tx-console .txk-msgs { flex:1; overflow:auto; padding:16px; display:flex; flex-direction:column; gap:10px; background:var(--bg-color); }
				.tx-console .txk-m { max-width:76%; padding:8px 12px; border-radius:12px; background:var(--card-bg); border:1px solid var(--border-color); }
				.tx-console .txk-m.out { align-self:flex-end; background:var(--control-bg); }
				.tx-console .txk-m.note { align-self:center; max-width:90%; background:var(--yellow-50, #fefce8); border-style:dashed; }
				.tx-console .txk-m small { display:block; color:var(--text-muted); font-size:11px; margin-bottom:2px; }
				.tx-console .txk-m p:last-child { margin-bottom:0; }
				.tx-console .txk-fail { color:var(--red-600, #dc2626); font-size:11px; }
				.tx-console .txk-compose { border-top:1px solid var(--border-color); padding:10px 12px; display:grid; gap:8px; }
				.tx-console .txk-compose textarea { width:100%; resize:vertical; min-height:64px; }
				.tx-console .txk-compose.note textarea { background:var(--yellow-50, #fefce8); }
				.tx-console .txk-bar { display:flex; justify-content:space-between; gap:8px; align-items:center; flex-wrap:wrap; }
				.tx-console .txk-empty { margin:auto; color:var(--text-muted); text-align:center; padding:40px; }
				@media (max-width: 900px) { .tx-console .txk { grid-template-columns:1fr; height:auto; }
					.tx-console .txk-side { max-height:40vh; } .tx-console .txk-main { min-height:60vh; } }
			</style>
			<div class="txk">
				<div class="txk-side">
					<div class="txk-filters">
						<input type="search" class="form-control input-sm txk-search" placeholder="${__("Search name, number, email")}">
						<div class="txk-tabs txk-channel">
							<button data-v="" class="on">${__("All")}</button>
							<button data-v="Live Chat">${__("Live chat")}</button>
							<button data-v="WhatsApp">${__("WhatsApp")}</button>
							<button data-v="Portal">${__("Portal")}</button>
						</div>
						<div class="txk-tabs txk-status">
							<button data-v="active" class="on">${__("Active")}</button>
							<button data-v="Open">${__("Needs reply")}</button>
							<button data-v="Closed">${__("Closed")}</button>
							<button data-mine="1">${__("Mine")}</button>
						</div>
					</div>
					<div class="txk-list"></div>
				</div>
				<div class="txk-main"><div class="txk-empty">${__("Select a conversation")}</div></div>
			</div>`);
		this.$list = $b.find(".txk-list");
		this.$main = $b.find(".txk-main");
		$b.find(".txk-channel button").on("click", (e) => {
			$b.find(".txk-channel button").removeClass("on");
			$(e.currentTarget).addClass("on");
			this.filters.channel = e.currentTarget.dataset.v;
			this.refresh();
		});
		$b.find(".txk-status button").on("click", (e) => {
			const el = e.currentTarget;
			if (el.dataset.mine) {
				$(el).toggleClass("on");
				this.filters.mine = $(el).hasClass("on") ? 1 : 0;
			} else {
				$b.find(".txk-status button:not([data-mine])").removeClass("on");
				$(el).addClass("on");
				this.filters.status = el.dataset.v;
			}
			this.refresh();
		});
		$b.find(".txk-search").on("input", frappe.utils.debounce((e) => {
			this.filters.search = e.target.value;
			this.refresh();
		}, 350));
	}

	show(name) {
		if (name) this.open(name);
	}

	onEvent(d) {
		this.refresh(true);
		if (this.active && d && d.conversation === this.active) this.loadThread(true);
	}

	refresh(quiet) {
		frappe.call({ method: API + "inbox", args: this.filters, type: "GET", quiet }).then((r) => this.renderList(r.message || []));
	}

	renderList(rows) {
		const esc = frappe.utils.escape_html;
		const unread = rows.reduce((s, r) => s + (r.unread_agent || 0), 0);
		document.title = (unread ? `(${unread}) ` : "") + __("Support Chat");
		if (!rows.length) {
			this.$list.html(`<div class="txk-empty">${__("No conversations")}</div>`);
			return;
		}
		this.$list.html(rows.map((r) => {
			const initials = (r.display_name || "?").replace("+", "").split(" ").map((x) => x[0]).slice(0, 2).join("").toUpperCase();
			const cls = (r.channel || "Portal").split(" ")[0];
			return `<div class="txk-item ${r.name === this.active ? "on" : ""}" data-name="${esc(r.name)}">
				<div class="txk-av ${cls}" title="${esc(CHANNEL_LABEL[r.channel] || r.channel)}">${esc(initials || "?")}</div>
				<div style="min-width:0">
					<div class="txk-name">${esc(r.display_name || r.subject)}</div>
					<div class="txk-prev">${esc(r.preview || "")}</div>
					<div class="txk-prev">${esc(CHANNEL_LABEL[r.channel] || "")}${r.customer ? " · " + esc(r.customer) : r.is_guest ? " · " + __("Guest") : ""}</div>
				</div>
				<div class="txk-meta">
					<span>${r.last_activity_at ? frappe.datetime.comment_when(r.last_activity_at, true) : ""}</span>
					${r.unread_agent ? `<span class="txk-badge">${r.unread_agent}</span>` : r.status === "Closed" ? __("Closed") : ""}
				</div>
			</div>`;
		}).join(""));
		this.$list.find(".txk-item").on("click", (e) => this.open(e.currentTarget.dataset.name));
	}

	open(name) {
		this.active = name;
		this.$list.find(".txk-item").removeClass("on").filter(`[data-name="${CSS.escape(name)}"]`).addClass("on");
		this.loadThread();
	}

	loadThread(quiet) {
		const name = this.active;
		frappe.call({ method: API + "thread", args: { name }, type: "GET", quiet }).then((r) => {
			if (this.active === name) this.renderThread(r.message);
		});
	}

	renderThread(data) {
		const esc = frappe.utils.escape_html;
		const c = data.conversation;
		const keepDraft = this.$main.find("textarea").val() || "";
		const pills = [];
		pills.push(`<span class="txk-pill">${esc(CHANNEL_LABEL[c.channel] || c.channel)}</span>`);
		pills.push(`<span class="txk-pill">${esc(__(c.status))}</span>`);
		if (c.channel === "WhatsApp") {
			pills.push(c.window_open
				? `<span class="txk-pill ok">${__("Reply window open until {0}", [frappe.datetime.str_to_user(c.whatsapp_window_expires)])}</span>`
				: `<span class="txk-pill warn">${__("24-hour window closed: replies are sent as the template")}</span>`);
		}
		if (c.is_guest && c.channel === "Live Chat") {
			pills.push(c.visitor_online ? `<span class="txk-pill ok">${__("Visitor online")}</span>` : `<span class="txk-pill">${__("Visitor away")}</span>`);
		}
		const who = [];
		if (c.guest_email) who.push(esc(c.guest_email));
		if (c.guest_phone) who.push(esc(c.guest_phone));
		if (c.whatsapp_number) who.push("+" + esc(c.whatsapp_number));
		if (c.customer) who.push(`<a href="/app/customer/${encodeURIComponent(c.customer)}">${esc(c.customer_name || c.customer)}</a>`);
		if (c.source_page) who.push(esc(c.source_page));
		if (c.helpdesk_ticket) who.push(`<a href="/helpdesk/tickets/${encodeURIComponent(c.helpdesk_ticket)}">#${esc(c.helpdesk_ticket)}</a>`);

		const msgs = (data.messages || []).map((m) => {
			const cls = m.is_internal ? "note" : m.direction === "Outbound" ? "out" : "in";
			const status = m.direction === "Outbound" && m.delivery_status ? ` · ${esc(__(m.delivery_status))}` : "";
			const fail = m.delivery_status === "Failed"
				? `<div class="txk-fail">${esc(m.delivery_error || __("Not delivered"))} <a href="#" data-retry="${esc(m.name)}">${__("Retry")}</a></div>`
				: m.delivery_error ? `<div class="text-muted small">${esc(m.delivery_error)}</div>` : "";
			const att = m.attachment ? `<div><a href="${esc(m.attachment)}" target="_blank" rel="noopener">${__("Attachment")}</a></div>` : "";
			return `<div class="txk-m ${cls}"><small>${esc(m.sender_name || "")}${m.is_internal ? " · " + __("Internal note") : ""} · ${frappe.datetime.comment_when(m.creation, true)}${status}</small>${m.content || ""}${att}${fail}</div>`;
		}).join("") || `<div class="txk-empty">${__("No messages yet")}</div>`;

		this.$main.html(`
			<div class="txk-head">
				<div><h4>${esc(c.display_name || c.subject)}</h4><div>${pills.join("")}</div><small>${who.join(" · ")}</small></div>
				<div class="btn-group">
					${c.assigned_agent === frappe.session.user ? "" : `<button class="btn btn-default btn-xs" data-act="assign">${__("Assign to me")}</button>`}
					${!c.customer ? `<button class="btn btn-default btn-xs" data-act="link">${__("Link customer")}</button>` : ""}
					${!c.helpdesk_ticket ? `<button class="btn btn-default btn-xs" data-act="ticket">${__("Create ticket")}</button>` : ""}
					${c.status === "Closed"
						? `<button class="btn btn-default btn-xs" data-act="reopen">${__("Reopen")}</button>`
						: `<button class="btn btn-default btn-xs" data-act="close">${__("Close")}</button>`}
					<button class="btn btn-default btn-xs" data-act="form">${__("Open form")}</button>
				</div>
			</div>
			<div class="txk-msgs">${msgs}</div>
			<div class="txk-compose ${this.internal ? "note" : ""}">
				<textarea class="form-control" placeholder="${this.internal ? __("Internal note: only agents see this") : __("Reply to the customer. Enter sends, Shift+Enter adds a line.")}"></textarea>
				<div class="txk-bar">
					<label class="small"><input type="checkbox" class="txk-internal" ${this.internal ? "checked" : ""}> ${__("Internal note")}</label>
					<button class="btn btn-primary btn-sm txk-send">${__("Send")}</button>
				</div>
			</div>`);
		const $msgs = this.$main.find(".txk-msgs");
		$msgs.scrollTop($msgs[0].scrollHeight);
		const $ta = this.$main.find("textarea").val(keepDraft);
		$ta.on("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); this.send(); } });
		this.$main.find(".txk-send").on("click", () => this.send());
		this.$main.find(".txk-internal").on("change", (e) => {
			this.internal = e.target.checked ? 1 : 0;
			this.$main.find(".txk-compose").toggleClass("note", !!this.internal);
		});
		this.$main.find("[data-retry]").on("click", (e) => {
			e.preventDefault();
			frappe.call({ method: API + "retry", args: { message: e.currentTarget.dataset.retry } }).then(() => this.loadThread(true));
		});
		this.$main.find("[data-act]").on("click", (e) => this.action(e.currentTarget.dataset.act, c));
	}

	send() {
		const $ta = this.$main.find("textarea");
		const text = ($ta.val() || "").trim();
		if (!text) return;
		const html = text.split(/\n{2,}/).map((p) => `<p>${frappe.utils.escape_html(p).replace(/\n/g, "<br>")}</p>`).join("");
		$ta.val("").prop("disabled", true);
		frappe.call({ method: API + "reply", args: { name: this.active, content: html, internal: this.internal } })
			.then(() => this.loadThread(true))
			.catch(() => $ta.val(text))
			.finally(() => $ta.prop("disabled", false).trigger("focus"));
	}

	action(act, c) {
		const name = c.name;
		const reload = () => { this.loadThread(true); this.refresh(true); };
		const DOC = "thinknxg_support.thinknxg_support.doctype.support_conversation_link.support_conversation_link.";
		if (act === "assign") frappe.call({ method: API + "assign", args: { name } }).then(reload);
		if (act === "close") frappe.call({ method: API + "set_status", args: { name, status: "Closed" } }).then(reload);
		if (act === "reopen") frappe.call({ method: API + "set_status", args: { name, status: "Open" } }).then(reload);
		if (act === "form") frappe.set_route("Form", "Support Conversation Link", name);
		if (act === "ticket") frappe.call({ method: DOC + "escalate", args: { name }, freeze: true }).then(reload);
		if (act === "link") {
			frappe.prompt([
				{ fieldname: "customer", fieldtype: "Link", options: "Customer", label: __("Customer"), reqd: 1 },
				{ fieldname: "contact", fieldtype: "Link", options: "Contact", label: __("Contact"),
					description: __("Only link after confirming who the visitor is.") },
			], (v) => frappe.call({ method: DOC + "link_customer", args: { name, ...v } }).then(reload), __("Link customer"));
		}
	}
}
