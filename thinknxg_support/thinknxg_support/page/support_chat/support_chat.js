// thinkNXG Support - agent chat console: one inbox for portal messages, live chat and WhatsApp,
// with the AI assistant and chatbot working in front of the team.
const API = "thinknxg_support.api.v1.agent.";
const DOCM = "thinknxg_support.thinknxg_support.doctype.support_conversation_link.support_conversation_link.";
const CHANNEL_LABEL = { Portal: __("Portal"), "Live Chat": __("Live chat"), WhatsApp: __("WhatsApp") };
const HANDLING_LABEL = { Bot: __("Assistant"), Queued: __("Waiting for agent"), Agent: __("Agent") };
const SENDER_BADGE = { AI: __("AI"), Bot: __("Bot"), System: __("System") };

frappe.pages["support-chat"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Support Chat"), single_column: true });
	wrapper.console = new SupportChatConsole(page, wrapper);
};

frappe.pages["support-chat"].on_page_show = function (wrapper) {
	const want = (frappe.route_options && frappe.route_options.conversation) || null;
	frappe.route_options = null;
	if (wrapper.console) wrapper.console.show(want);
};

class SupportChatConsole {
	constructor(page) {
		this.page = page;
		this.filters = { status: "active", channel: "", mine: 0, search: "", queue: "" };
		this.active = null;
		this.internal = 0;
		this.lastTyping = 0;
		this.build();
		this.page.set_secondary_action(__("Settings"), () => frappe.set_route("Form", "Support Portal Settings"));
		this.page.add_menu_item(__("AI Assistant Settings"), () => frappe.set_route("Form", "Support AI Settings"));
		this.page.add_menu_item(__("Chatbots"), () => frappe.set_route("List", "Support Chatbot"));
		this.page.add_menu_item(__("Queues"), () => frappe.set_route("List", "Support Chat Queue"));
		this.page.add_menu_item(__("Live Chat Performance"), () => frappe.set_route("query-report", "Live Chat Performance"));
		frappe.realtime.doctype_subscribe && frappe.realtime.doctype_subscribe("Support Conversation Link");
		frappe.realtime.on("thinknxg_support_chat", (d) => this.onEvent(d));
		this.timer = setInterval(() => !document.hidden && this.refresh(true), 15000);
		this.liveTimer = setInterval(() => !document.hidden && this.active && this.pollLive(), 2000);
		this.beat();
		this.beatTimer = setInterval(() => this.beat(), 30000);
		frappe.call({ method: API + "queues", type: "GET" }).then((r) => this.fillQueues(r.message || []));
		this.refresh();
	}

	beat() {
		if (!document.hidden) frappe.call({ method: API + "heartbeat", quiet: true });
	}

	build() {
		const $b = $(this.page.body).addClass("tx-console");
		$b.html(`
			<style>
				.tx-console .txk { display:grid; grid-template-columns: 350px minmax(0,1fr); height: calc(100vh - 160px);
					min-height:540px; border:1px solid var(--border-color); border-radius:var(--border-radius-lg); overflow:hidden; background:var(--card-bg); }
				.tx-console .txk-side { border-inline-end:1px solid var(--border-color); display:flex; flex-direction:column; min-height:0; }
				.tx-console .txk-filters { padding:10px; display:grid; gap:8px; border-bottom:1px solid var(--border-color); }
				.tx-console .txk-tabs { display:flex; gap:4px; flex-wrap:wrap; }
				.tx-console .txk-tabs button { border:1px solid var(--border-color); background:var(--bg-color); border-radius:999px;
					padding:2px 10px; font-size:var(--text-sm); color:var(--text-muted); }
				.tx-console .txk-tabs button.on { background:var(--primary); border-color:var(--primary); color:var(--white, #fff); }
				.tx-console .txk-tabs button .n { font-weight:700; margin-inline-start:4px; }
				.tx-console .txk-list { overflow:auto; flex:1; }
				.tx-console .txk-item { display:grid; grid-template-columns:auto 1fr auto; gap:10px; padding:10px 12px; cursor:pointer;
					border-bottom:1px solid var(--border-color); align-items:start; }
				.tx-console .txk-item:hover { background:var(--subtle-fg); }
				.tx-console .txk-item.on { background:var(--control-bg); }
				.tx-console .txk-item.waiting { box-shadow: inset 3px 0 0 var(--orange-500, #f97316); }
				.tx-console .txk-av { width:34px; height:34px; border-radius:50%; display:grid; place-items:center; font-weight:600; font-size:12px; color:#fff; }
				.tx-console .txk-av.Portal { background:#2563eb; } .tx-console .txk-av.Live { background:#0f766e; } .tx-console .txk-av.WhatsApp { background:#128c7e; }
				.tx-console .txk-name { font-weight:600; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
				.tx-console .txk-prev { color:var(--text-muted); font-size:var(--text-sm); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
				.tx-console .txk-meta { text-align:end; font-size:var(--text-xs); color:var(--text-muted); display:grid; gap:4px; justify-items:end; }
				.tx-console .txk-badge { background:var(--primary); color:#fff; border-radius:999px; min-width:20px; padding:0 6px; font-size:11px; font-weight:700; text-align:center; }
				.tx-console .txk-main { display:flex; flex-direction:column; min-width:0; min-height:0; }
				.tx-console .txk-head { padding:12px 16px; border-bottom:1px solid var(--border-color); display:flex; gap:12px; justify-content:space-between; align-items:flex-start; flex-wrap:wrap; }
				.tx-console .txk-head h4 { margin:0 0 2px; }
				.tx-console .txk-head small { color:var(--text-muted); }
				.tx-console .txk-pill { display:inline-block; border-radius:999px; padding:1px 8px; font-size:11px; font-weight:600; background:var(--bg-color); border:1px solid var(--border-color); margin-inline-end:4px; }
				.tx-console .txk-pill.ok { color:var(--green-600, #15803d); } .tx-console .txk-pill.warn { color:var(--orange-600, #c2410c); }
				.tx-console .txk-pill.bot { color:var(--blue-600, #2563eb); }
				.tx-console .txk-msgs { flex:1; overflow:auto; padding:16px; display:flex; flex-direction:column; gap:10px; background:var(--bg-color); }
				.tx-console .txk-m { max-width:76%; padding:8px 12px; border-radius:12px; background:var(--card-bg); border:1px solid var(--border-color); }
				.tx-console .txk-m.out { align-self:flex-end; background:var(--control-bg); }
				.tx-console .txk-m.ai, .tx-console .txk-m.bot { align-self:flex-end; background:var(--card-bg); border-style:dashed; }
				.tx-console .txk-m.sys { align-self:center; max-width:90%; background:transparent; border:0; color:var(--text-muted); font-size:var(--text-sm); text-align:center; padding:2px 8px; }
				.tx-console .txk-m.note { align-self:center; max-width:90%; background:var(--yellow-50, #fefce8); border-style:dashed; }
				.tx-console .txk-m small { display:block; color:var(--text-muted); font-size:11px; margin-bottom:2px; }
				.tx-console .txk-m p:last-child { margin-bottom:0; }
				.tx-console .txk-tag { display:inline-block; font-size:10px; font-weight:700; padding:0 6px; border-radius:4px; margin-inline-end:4px; background:var(--blue-100, #dbeafe); color:var(--blue-700, #1d4ed8); }
				.tx-console .txk-extra { margin-top:6px; font-size:11px; color:var(--text-muted); }
				.tx-console .txk-extra span { margin-inline-end:8px; }
				.tx-console .txk-fail { color:var(--red-600, #dc2626); font-size:11px; }
				.tx-console .txk-live { min-height:20px; padding:0 16px; font-size:12px; color:var(--text-muted); }
				.tx-console .txk-compose { border-top:1px solid var(--border-color); padding:10px 12px; display:grid; gap:8px; }
				.tx-console .txk-compose textarea { width:100%; resize:vertical; min-height:64px; }
				.tx-console .txk-compose.note textarea { background:var(--yellow-50, #fefce8); }
				.tx-console .txk-banner { padding:8px 12px; border-radius:8px; background:var(--blue-50, #eff6ff); font-size:12px; display:flex; gap:8px; align-items:center; justify-content:space-between; flex-wrap:wrap; }
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
							<button data-v="waiting_agent">${__("Waiting for agent")}<span class="n txk-n-waiting"></span></button>
							<button data-v="Open">${__("Needs reply")}</button>
							<button data-v="bot">${__("With assistant")}</button>
							<button data-v="Closed">${__("Closed")}</button>
							<button data-mine="1">${__("Mine")}</button>
						</div>
						<select class="form-control input-sm txk-queue"><option value="">${__("All queues")}</option></select>
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
		$b.find(".txk-queue").on("change", (e) => {
			this.filters.queue = e.target.value;
			this.refresh();
		});
		$b.find(".txk-search").on("input", frappe.utils.debounce((e) => {
			this.filters.search = e.target.value;
			this.refresh();
		}, 350));
	}

	fillQueues(names) {
		const esc = frappe.utils.escape_html;
		this.$list.closest(".txk").find(".txk-queue").append(names.map((n) => `<option value="${esc(n)}">${esc(n)}</option>`).join(""));
	}

	show(name) {
		if (name) this.open(name);
	}

	onEvent(d) {
		this.refresh(true);
		if (this.active && d && d.conversation === this.active) this.loadThread(true);
		if (d && d.kind === "handoff" && d.conversation !== this.active) frappe.utils.play_sound && frappe.utils.play_sound("alert");
	}

	refresh(quiet) {
		frappe.call({ method: API + "inbox", args: this.filters, type: "GET", quiet }).then((r) => this.renderList(r.message || []));
		frappe.call({ method: API + "summary", type: "GET", quiet: true }).then((r) => {
			const s = r.message || {};
			this.$list.closest(".txk").find(".txk-n-waiting").text(s.waiting_agent ? s.waiting_agent : "");
		});
	}

	renderList(rows) {
		const esc = frappe.utils.escape_html;
		const unread = rows.reduce((s, r) => s + (r.handling === "Bot" ? 0 : r.unread_agent || 0), 0);
		document.title = (unread ? `(${unread}) ` : "") + __("Support Chat");
		if (!rows.length) {
			this.$list.html(`<div class="txk-empty">${__("No conversations")}</div>`);
			return;
		}
		this.$list.html(rows.map((r) => {
			const initials = (r.display_name || "?").replace("+", "").split(" ").map((x) => x[0]).slice(0, 2).join("").toUpperCase();
			const cls = (r.channel || "Portal").split(" ")[0];
			const who = r.customer ? esc(r.customer) : r.is_guest ? __("Guest") : "";
			const state = r.status === "Closed" ? __("Closed") : HANDLING_LABEL[r.handling] || "";
			return `<div class="txk-item ${r.name === this.active ? "on" : ""} ${r.handling === "Queued" && r.status !== "Closed" ? "waiting" : ""}" data-name="${esc(r.name)}">
				<div class="txk-av ${cls}" title="${esc(CHANNEL_LABEL[r.channel] || r.channel)}">${esc(initials || "?")}</div>
				<div style="min-width:0">
					<div class="txk-name">${esc(r.display_name || r.subject)}</div>
					<div class="txk-prev">${r.customer_typing ? `<i>${__("typing…")}</i>` : esc(r.preview || "")}</div>
					<div class="txk-prev">${esc(CHANNEL_LABEL[r.channel] || "")}${who ? " · " + who : ""}${r.queue ? " · " + esc(r.queue) : ""}</div>
				</div>
				<div class="txk-meta">
					<span>${r.last_activity_at ? frappe.datetime.comment_when(r.last_activity_at, true) : ""}</span>
					${r.unread_agent && r.handling !== "Bot" ? `<span class="txk-badge">${r.unread_agent}</span>` : `<span>${esc(state)}</span>`}
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

	pollLive() {
		const name = this.active;
		frappe.call({ method: API + "live", args: { name }, type: "GET", quiet: true }).then((r) => {
			if (this.active !== name) return;
			const s = r.message || {};
			const bits = [];
			if (s.customer_typing) bits.push(__("Customer is typing…"));
			if (s.ai_drafting) bits.push(__("Assistant is writing a reply…"));
			this.$main.find(".txk-live").text(bits.join(" · "));
		});
	}

	messageHtml(m) {
		const esc = frappe.utils.escape_html;
		const st = m.sender_type || (m.direction === "Inbound" ? "Customer" : "Agent");
		if (st === "System" && !m.is_internal) return `<div class="txk-m sys">${m.content || ""}</div>`;
		const cls = m.is_internal ? "note" : m.direction === "Inbound" ? "in" : st === "AI" ? "out ai" : st === "Bot" ? "out bot" : "out";
		const tag = SENDER_BADGE[st] && !m.is_internal ? `<span class="txk-tag">${esc(SENDER_BADGE[st])}</span>` : "";
		let status = "";
		if (m.direction === "Outbound" && m.delivery_status) status = ` · ${esc(__(m.delivery_status))}`;
		else if (m.direction === "Outbound" && !m.is_internal && m.read_by_customer) status = ` · ${__("Seen")}`;
		const fail = m.delivery_status === "Failed"
			? `<div class="txk-fail">${esc(m.delivery_error || __("Not delivered"))} <a href="#" data-retry="${esc(m.name)}">${__("Retry")}</a></div>`
			: m.delivery_error ? `<div class="text-muted small">${esc(m.delivery_error)}</div>` : "";
		const att = m.attachment ? `<div><a href="${esc(m.attachment)}" target="_blank" rel="noopener">${__("Attachment")}</a></div>` : "";
		const a = m.actions || {};
		const extra = [];
		if (st === "AI" && m.confidence) extra.push(`<span>${__("Confidence")}: ${esc(__(m.confidence))}</span>`);
		if (a.sources && a.sources.length) extra.push(`<span>${__("Sources")}: ${a.sources.map((s) => esc(s.title)).join(", ")}</span>`);
		if (a.buttons && a.buttons.length) extra.push(`<span>${__("Buttons")}: ${a.buttons.map((b) => esc(b.label)).join(", ")}</span>`);
		if (a.follow_ups && a.follow_ups.length) extra.push(`<span>${__("Suggested")}: ${a.follow_ups.map((f) => esc(f)).join(" | ")}</span>`);
		if (m.feedback) extra.push(`<span>${__("Customer rated")}: ${esc(__(m.feedback))}</span>`);
		if (m.response_source && st === "Bot") extra.push(`<span>${__("Rule")}: ${esc(m.response_source)}</span>`);
		return `<div class="txk-m ${cls}"><small>${tag}${esc(m.sender_name || "")}${m.is_internal ? " · " + __("Internal note") : ""} · ${frappe.datetime.comment_when(m.creation, true)}${status}</small>${m.content || ""}${att}${fail}${extra.length ? `<div class="txk-extra">${extra.join("")}</div>` : ""}</div>`;
	}

	renderThread(data) {
		const esc = frappe.utils.escape_html;
		const c = data.conversation;
		const keepDraft = this.$main.find("textarea").val() || "";
		const pills = [];
		pills.push(`<span class="txk-pill">${esc(CHANNEL_LABEL[c.channel] || c.channel)}</span>`);
		pills.push(`<span class="txk-pill">${esc(__(c.status))}</span>`);
		if (c.handling) {
			const cls = c.handling === "Bot" ? "bot" : c.handling === "Queued" ? "warn" : "ok";
			const label = c.handling === "Agent" && c.assigned_name ? `${__("Agent")}: ${c.assigned_name}` : HANDLING_LABEL[c.handling];
			pills.push(`<span class="txk-pill ${cls}">${esc(label)}</span>`);
		}
		if (c.queue) pills.push(`<span class="txk-pill">${esc(c.queue)}</span>`);
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
		if (c.handoff_reason) who.push(`${__("Handed over")}: ${esc(c.handoff_reason)}`);

		const msgs = (data.messages || []).map((m) => this.messageHtml(m)).join("") || `<div class="txk-empty">${__("No messages yet")}</div>`;
		const banner = c.handling === "Bot" && c.status !== "Closed"
			? `<div class="txk-banner"><span>${__("The assistant is answering this customer. Take over to reply yourself; it stops answering.")}</span>
				<button class="btn btn-primary btn-xs" data-act="takeover">${__("Take over")}</button></div>` : "";

		this.$main.html(`
			<div class="txk-head">
				<div><h4>${esc(c.display_name || c.subject)}</h4><div>${pills.join("")}</div><small>${who.join(" · ")}</small></div>
				<div class="btn-group">
					${c.handling !== "Bot" && c.assigned_agent !== frappe.session.user ? `<button class="btn btn-default btn-xs" data-act="assign">${__("Assign to me")}</button>` : ""}
					${c.handling === "Agent" && c.status !== "Closed" ? `<button class="btn btn-default btn-xs" data-act="tobot">${__("Return to assistant")}</button>` : ""}
					<button class="btn btn-default btn-xs" data-act="transfer">${__("Transfer")}</button>
					${!c.customer ? `<button class="btn btn-default btn-xs" data-act="link">${__("Link customer")}</button>` : ""}
					${!c.helpdesk_ticket ? `<button class="btn btn-default btn-xs" data-act="ticket">${__("Create ticket")}</button>` : ""}
					${c.status === "Closed"
						? `<button class="btn btn-default btn-xs" data-act="reopen">${__("Reopen")}</button>`
						: `<button class="btn btn-default btn-xs" data-act="close">${__("Close")}</button>`}
					<button class="btn btn-default btn-xs" data-act="form">${__("Open form")}</button>
				</div>
			</div>
			<div class="txk-msgs">${msgs}</div>
			<div class="txk-live"></div>
			<div class="txk-compose ${this.internal ? "note" : ""}">
				${banner}
				<textarea class="form-control" placeholder="${this.internal ? __("Internal note: only agents see this") : __("Reply to the customer. Enter sends, Shift+Enter adds a line.")}"></textarea>
				<div class="txk-bar">
					<label class="small"><input type="checkbox" class="txk-internal" ${this.internal ? "checked" : ""}> ${__("Internal note")}</label>
					<button class="btn btn-primary btn-sm txk-send">${__("Send")}</button>
				</div>
			</div>`);
		const $msgs = this.$main.find(".txk-msgs");
		$msgs.scrollTop($msgs[0].scrollHeight);
		const $ta = this.$main.find("textarea").val(keepDraft);
		$ta.on("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); this.send(c); } });
		$ta.on("input", () => {
			if (this.internal || Date.now() - this.lastTyping < 3000) return;
			this.lastTyping = Date.now();
			frappe.call({ method: API + "typing", args: { name: c.name }, quiet: true });
		});
		this.$main.find(".txk-send").on("click", () => this.send(c));
		this.$main.find(".txk-internal").on("change", (e) => {
			this.internal = e.target.checked ? 1 : 0;
			this.$main.find(".txk-compose").toggleClass("note", !!this.internal);
		});
		this.$main.find("[data-retry]").on("click", (e) => {
			e.preventDefault();
			frappe.call({ method: API + "retry", args: { message: e.currentTarget.dataset.retry } }).then(() => this.loadThread(true));
		});
		this.$main.find("[data-act]").on("click", (e) => this.action(e.currentTarget.dataset.act, c));
		this.pollLive();
	}

	send(c) {
		const $ta = this.$main.find("textarea");
		const text = ($ta.val() || "").trim();
		if (!text) return;
		const go = () => {
			const html = text.split(/\n{2,}/).map((p) => `<p>${frappe.utils.escape_html(p).replace(/\n/g, "<br>")}</p>`).join("");
			$ta.val("").prop("disabled", true);
			frappe.call({ method: API + "reply", args: { name: this.active, content: html, internal: this.internal } })
				.then(() => this.loadThread(true))
				.catch(() => $ta.val(text))
				.finally(() => $ta.prop("disabled", false).trigger("focus"));
		};
		if (!this.internal && c.handling === "Bot") {
			frappe.call({ method: API + "take_over", args: { name: c.name } }).then(go);
		} else go();
	}

	action(act, c) {
		const name = c.name;
		const reload = () => { this.loadThread(true); this.refresh(true); };
		if (act === "assign") frappe.call({ method: API + "assign", args: { name } }).then(reload);
		if (act === "takeover") frappe.call({ method: API + "take_over", args: { name } }).then(reload);
		if (act === "tobot") frappe.call({ method: API + "return_to_assistant", args: { name } }).then(reload);
		if (act === "close") frappe.call({ method: API + "set_status", args: { name, status: "Closed" } }).then(reload);
		if (act === "reopen") frappe.call({ method: API + "set_status", args: { name, status: "Open" } }).then(reload);
		if (act === "form") frappe.set_route("Form", "Support Conversation Link", name);
		if (act === "ticket") frappe.call({ method: DOCM + "escalate", args: { name }, freeze: true }).then(reload);
		if (act === "transfer") {
			frappe.prompt([
				{ fieldname: "user", fieldtype: "Link", options: "User", label: __("Agent"),
					description: __("Leave empty to let the queue pick an agent") },
				{ fieldname: "queue", fieldtype: "Link", options: "Support Chat Queue", label: __("Queue") },
			], (v) => frappe.call({ method: API + "transfer", args: { name, ...v } }).then(reload), __("Transfer chat"));
		}
		if (act === "link") {
			frappe.prompt([
				{ fieldname: "customer", fieldtype: "Link", options: "Customer", label: __("Customer"), reqd: 1 },
				{ fieldname: "contact", fieldtype: "Link", options: "Contact", label: __("Contact"),
					description: __("Only link after confirming who the visitor is.") },
			], (v) => frappe.call({ method: DOCM + "link_customer", args: { name, ...v } }).then(reload), __("Link customer"));
		}
	}
}
