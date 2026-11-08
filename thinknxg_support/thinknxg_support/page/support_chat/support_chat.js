// thinkNXG Support - agent chat console: one inbox for portal messages, live chat and WhatsApp,
// with the AI assistant and chatbot working in front of the team.
const API = "thinknxg_support.api.v1.agent.";
const DOCM = "thinknxg_support.thinknxg_support.doctype.support_conversation_link.support_conversation_link.";
const TOOLS = "thinknxg_support.integrations.agent_tools.";
const COPILOT = "thinknxg_support.api.v1.copilot.";

// Canned response text for the reply box: HTML to plain text, placeholders filled from the chat.
function cannedText(html, c) {
	const div = document.createElement("div");
	div.innerHTML = (html || "").replace(/<\/(p|div|li|h[1-6])>/gi, "\n\n").replace(/<br\s*\/?>/gi, "\n");
	const name = (c.display_name || "").replace(/^\+/, "");
	const vals = {
		customer_name: name, customer_first_name: name.split(" ")[0] || name,
		agent_name: frappe.session.user_fullname || "", agent_first_name: (frappe.session.user_fullname || "").split(" ")[0],
		company: (frappe.boot.sysdefaults && frappe.boot.sysdefaults.company) || "", ticket: c.helpdesk_ticket || "",
		conversation: c.name || "",
	};
	return (div.textContent || "").replace(/\{(\w+)\}/g, (m, k) => (k in vals ? vals[k] : m)).replace(/\n{3,}/g, "\n\n").trim();
}
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
		// 1.14: my status (only Available agents get new chats), and whether I am using the console
		this.activeSinceBeat = true;
		["mousemove", "keydown", "click", "scroll"].forEach((ev) => document.addEventListener(ev, () => { this.activeSinceBeat = true; }, { passive: true }));
		this.statusField = this.page.add_field({ fieldname: "agent_status", label: __("My status"), fieldtype: "Select",
			options: ["Available", "Away", "Busy", "Offline"].map((v) => ({ value: v, label: __(v) })), default: "Available",
			change: () => this.setStatus(this.statusField.get_value()) });
		this.beat();
		this.beatTimer = setInterval(() => this.beat(), 30000);
		frappe.call({ method: API + "queues", type: "GET" }).then((r) => this.fillQueues(r.message || []));
		this.refresh();
	}

	beat() {
		if (document.hidden) return;
		const active = this.activeSinceBeat ? 1 : 0;
		this.activeSinceBeat = false;
		frappe.call({ method: API + "heartbeat", args: { active }, quiet: true }).then((r) => this.showStatus(r.message));
	}

	setStatus(status) {
		if (!status || this.settingStatus || (this.myStatus && this.myStatus.set_status === status)) return;
		frappe.call({ method: API + "set_agent_status", args: { status }, quiet: true }).then((r) => {
			this.showStatus(r.message);
			frappe.show_alert({ message: status === "Available" ? __("You get new chats.") : __("You keep your chats and get no new ones."), indicator: status === "Available" ? "green" : "orange" });
		});
	}

	showStatus(s) {
		if (!s || !s.status || !this.statusField) return;
		this.myStatus = s;
		this.settingStatus = true;
		this.statusField.set_value(s.set_status || s.status).finally(() => { this.settingStatus = false; });
		const colour = { Available: "green", Away: "orange", Busy: "red", Offline: "grey" }[s.status];
		const label = s.reason ? `${__(s.status)} (${__(s.reason)})` : __(s.status);
		this.page.set_indicator(label, colour);
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
				.tx-console .txk-canned { position:relative; }
				.tx-console .txk-suggest { position:absolute; inset-inline:12px; bottom:100%; margin-bottom:4px; max-height:240px; overflow:auto; background:var(--card-bg); border:1px solid var(--border-color); border-radius:8px; box-shadow:0 8px 24px rgba(0,0,0,.12); z-index:5; }
				.tx-console .txk-suggest button { display:block; width:100%; text-align:start; border:0; background:none; padding:7px 10px; font-size:12px; }
				.tx-console .txk-suggest button.on, .tx-console .txk-suggest button:hover { background:var(--control-bg); }
				.tx-console .txk-suggest b { margin-inline-end:6px; }
				.tx-console .txk-empty { margin:auto; color:var(--text-muted); text-align:center; padding:40px; }
				.tx-console .txk-quote { font-size:11px; color:var(--text-muted); border-inline-start:3px solid var(--primary); padding:1px 6px; margin:2px 0 4px; background:var(--subtle-fg); border-radius:4px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
				.tx-console .txk-thumb { max-width:220px; max-height:220px; border-radius:6px; display:block; margin-top:4px; background:var(--subtle-fg); min-width:80px; min-height:40px; }
				.tx-console .txk-audio { height:32px; max-width:240px; margin-top:4px; }
				.tx-console .txk-reacts { display:flex; gap:4px; flex-wrap:wrap; margin-top:4px; }
				.tx-console .txk-reacts button, .tx-console .txk-picker button { border:1px solid var(--border-color); background:var(--card-bg); border-radius:999px; padding:0 7px; font-size:12px; }
				.tx-console .txk-reacts button.on { border-color:var(--primary); }
				.tx-console .txk-picker { display:flex; gap:4px; margin-top:4px; }
				.tx-console .txk-acts { margin-inline-start:8px; opacity:0; } .tx-console .txk-m:hover .txk-acts { opacity:1; }
				.tx-console .txk-acts a { margin-inline-start:4px; color:var(--text-muted); }
				.tx-console .txk-m.gone > :not(small):not(.txk-removed) { opacity:.5; text-decoration:line-through; }
				.tx-console .txk-removed { font-size:11px; color:var(--orange-600, #c2410c); margin-top:4px; }
				.tx-console .txk-replybar { display:flex; justify-content:space-between; font-size:12px; border-inline-start:3px solid var(--primary); padding:2px 8px; background:var(--subtle-fg); border-radius:4px; }
				.tx-console .txk-file { font-size:12px; }
				.tx-console .txk-org { display:flex; gap:6px; align-items:center; flex-wrap:wrap; margin-top:4px; font-size:12px; }
				.tx-console .txk-priority { height:24px; padding:0 6px; font-size:12px; border-radius:6px; border:1px solid var(--border-color); background:var(--card-bg); }
				.tx-console .txk-tag { display:inline-block; background:var(--subtle-fg); border-radius:999px; padding:0 8px; font-size:11px; }
				.tx-console .txk-tag a { color:var(--text-muted); }
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
					${(r.priority === "High" || r.priority === "Urgent" || (r.tags || []).length) ? `<div class="txk-prev">${r.priority === "Urgent" || r.priority === "High" ? `<span class="indicator-pill ${r.priority === "Urgent" ? "red" : "orange"}">${__(r.priority)}</span> ` : ""}${(r.tags || []).map((t) => `<span class="txk-tag">${esc(t)}</span>`).join(" ")}</div>` : ""}
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
		const fileUrl = `/api/method/thinknxg_support.api.staff.v1.attachment?message=${encodeURIComponent(m.name)}`;
		const att = !m.attachment ? "" : m.attachment_kind === "image"
			? `<div><a href="${fileUrl}" target="_blank" rel="noopener"><img class="txk-thumb" data-img="${esc(m.name)}" alt="${__("Photo")}"></a></div>`
			: m.attachment_kind === "audio"
				? `<div><audio class="txk-audio" data-audio="${esc(m.name)}" controls preload="none"></audio>${m.voice_seconds ? ` <small>${__("Voice note")} · ${m.voice_seconds}s</small>` : ""}</div>`
				: `<div><a href="${fileUrl}" target="_blank" rel="noopener">📎 ${esc((m.attachment || "").split("/").pop() || __("Attachment"))}</a></div>`;
		const quote = m.reply ? `<div class="txk-quote"><b>${esc(m.reply.author || "")}</b> ${esc(m.reply.excerpt || "")}</div>` : "";
		const reacts = (m.reactions || []).length ? `<div class="txk-reacts">${m.reactions.map((r) =>
			`<button class="${r.mine ? "on" : ""}" data-react="${esc(m.name)}" data-emoji="${esc(r.emoji)}">${esc(r.emoji)} ${r.count}</button>`).join("")}</div>` : "";
		const removed = m.hidden ? `<div class="txk-removed">${__("Removed by {0}; the customer sees \"Message removed\"", [esc(m.hidden_by || "")])}</div>` : "";
		const acts = m.hidden ? "" : `<span class="txk-acts">
			<a href="#" data-reply="${esc(m.name)}" title="${__("Reply")}">↩</a>
			<a href="#" data-pick="${esc(m.name)}" title="${__("React")}">☺</a>
			${m.can_edit ? `<a href="#" data-edit="${esc(m.name)}" title="${__("Edit")}">✎</a>` : ""}
			${m.can_remove ? `<a href="#" data-remove="${esc(m.name)}" title="${__("Remove")}">🗑</a>` : ""}
			${m.edited_on ? `<a href="#" data-history="${esc(m.name)}" title="${__("Earlier versions")}">${__("edited")}</a>` : ""}</span>`;
		const a = m.actions || {};
		const extra = [];
		if (st === "AI" && m.confidence) extra.push(`<span>${__("Confidence")}: ${esc(__(m.confidence))}</span>`);
		if (a.sources && a.sources.length) extra.push(`<span>${__("Sources")}: ${a.sources.map((s) => esc(s.title)).join(", ")}</span>`);
		if (a.buttons && a.buttons.length) extra.push(`<span>${__("Buttons")}: ${a.buttons.map((b) => esc(b.label)).join(", ")}</span>`);
		if (a.follow_ups && a.follow_ups.length) extra.push(`<span>${__("Suggested")}: ${a.follow_ups.map((f) => esc(f)).join(" | ")}</span>`);
		if (m.feedback) extra.push(`<span>${__("Customer rated")}: ${esc(__(m.feedback))}</span>`);
		if (m.response_source && st === "Bot") extra.push(`<span>${__("Rule")}: ${esc(m.response_source)}</span>`);
		return `<div class="txk-m ${cls}${m.hidden ? " gone" : ""}" data-msg="${esc(m.name)}"><small>${tag}${esc(m.sender_name || "")}${m.is_internal ? " · " + __("Internal note") : ""} · ${frappe.datetime.comment_when(m.creation, true)}${status}${acts}</small>${quote}${m.content || ""}${att}${removed}${reacts}${fail}${extra.length ? `<div class="txk-extra">${extra.join("")}</div>` : ""}</div>`;
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
				<div><h4>${esc(c.display_name || c.subject)}</h4><div>${pills.join("")}</div><small>${who.join(" · ")}</small>
					<div class="txk-org">
						<select class="txk-priority input-xs" title="${__("Priority")}">${["Low", "Normal", "High", "Urgent"].map((p) => `<option value="${p}" ${(c.priority || "Normal") === p ? "selected" : ""}>${__("Priority")}: ${__(p)}</option>`).join("")}</select>
						${(c.tags || []).map((t) => `<span class="txk-tag">${esc(t)} <a href="#" data-untag="${esc(t)}" title="${__("Remove tag")}">×</a></span>`).join(" ")}
						<a href="#" class="txk-addtag">+ ${__("Tag")}</a>
					</div></div>
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
			<div class="txk-compose txk-canned ${this.internal ? "note" : ""}">
				<div class="txk-suggest" hidden></div>
				${banner}
				<div class="txk-replybar" hidden><span></span><a href="#" class="txk-replycancel">×</a></div>
				<div class="txk-file" hidden><span></span> <a href="#" class="txk-filecancel">${__("Remove")}</a></div>
				<textarea class="form-control" placeholder="${this.internal ? __("Internal note: only agents see this") : __("Reply to the customer. Enter sends, Shift+Enter adds a line.")}"></textarea>
				<div class="txk-bar">
					<label class="small"><input type="checkbox" class="txk-internal" ${this.internal ? "checked" : ""}> ${__("Internal note")}</label>
					<span>
						<span class="dropdown txk-ai">
							<button class="btn btn-default btn-sm dropdown-toggle" data-toggle="dropdown" data-bs-toggle="dropdown" title="${__("AI copilot: drafts only, you decide what is sent")}">${__("AI assist")}</button>
							<ul class="dropdown-menu dropdown-menu-right">
								<li><a class="dropdown-item" data-ai="suggest">${__("Suggest replies")}</a></li>
								<li><a class="dropdown-item" data-ai="rewrite:professional">${__("Rewrite: professional")}</a></li>
								<li><a class="dropdown-item" data-ai="rewrite:friendly">${__("Rewrite: friendly")}</a></li>
								<li><a class="dropdown-item" data-ai="rewrite:concise">${__("Rewrite: shorter")}</a></li>
								<li><a class="dropdown-item" data-ai="rewrite:fix">${__("Fix grammar")}</a></li>
								<li><a class="dropdown-item" data-ai="translate:customer">${__("Translate my draft to the customer's language")}</a></li>
								<li><a class="dropdown-item" data-ai="translate:last">${__("Translate the customer's last message")}</a></li>
								<li><a class="dropdown-item" data-ai="recommend">${__("Recommended solution and articles")}</a></li>
								<li><a class="dropdown-item" data-ai="summarize">${__("Summarise the conversation")}</a></li>
								<li><a class="dropdown-item" data-ai="note">${__("Add summary as internal note")}</a></li>
							</ul>
						</span>
						<button class="btn btn-default btn-sm txk-canned-btn" title="${__("Insert a canned response (or type / in the box)")}">${__("Canned responses")}</button>
						<label class="btn btn-default btn-sm" title="${__("Attach a file")}" style="margin:0">📎<input type="file" class="txk-attach" hidden></label>
						${(c.messaging || {}).voice && window.MediaRecorder ? `<button class="btn btn-default btn-sm txk-voice" title="${__("Record a voice note")}">🎤</button>` : ""}
						<button class="btn btn-primary btn-sm txk-send">${__("Send")}</button>
					</span>
				</div>
			</div>`);
		const $msgs = this.$main.find(".txk-msgs");
		$msgs.scrollTop($msgs[0].scrollHeight);
		const $ta = this.$main.find("textarea").val(keepDraft);
		$ta.on("keydown", (e) => {
			if (this.suggestKeys(e, c)) return;
			if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); this.send(c); }
		});
		$ta.on("input", () => this.suggest($ta, c));
		this.$main.find(".txk-canned-btn").on("click", () => this.cannedDialog(c));
		this.$main.find("[data-ai]").on("click", (e) => { e.preventDefault(); this.copilot(e.currentTarget.dataset.ai, c, data); });
		this.showInsight(c);
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
		this.bindMessageActions(c, data);
		this.bindOrganise(c);
		this.pollLive();
	}

	// ---------------------------------------------------------------- 1.14: reply, edit, remove, react, files, voice
	bindMessageActions(c, data) {
		const esc = frappe.utils.escape_html;
		const byName = Object.fromEntries((data.messages || []).map((m) => [m.name, m]));
		const $m = this.$main;
		const text = (m) => $("<div>").html(m.content || "").text().trim();
		this.replyTo = null;
		this.file = null;
		$m.find("[data-reply]").on("click", (e) => {
			e.preventDefault();
			const m = byName[e.currentTarget.dataset.reply];
			this.replyTo = m.name;
			$m.find(".txk-replybar").prop("hidden", false).find("span").html(`<b>${__("Replying to")} ${esc(m.sender_name || "")}</b> ${esc(text(m).slice(0, 80))}`);
			$m.find("textarea").trigger("focus");
		});
		$m.find(".txk-replycancel").on("click", (e) => { e.preventDefault(); this.replyTo = null; $m.find(".txk-replybar").prop("hidden", true); });
		const call = (method, args) => frappe.call({ method: API + method, args: Object.assign({ name: c.name }, args) }).then(() => this.loadThread(true));
		$m.find("[data-edit]").on("click", (e) => {
			e.preventDefault();
			const m = byName[e.currentTarget.dataset.edit];
			frappe.prompt({ fieldname: "text", fieldtype: "Small Text", label: __("Message"), reqd: 1, default: text(m) },
				(v) => call("edit_message", { message: m.name, text: v.text }), __("Edit message"), __("Save"));
		});
		$m.find("[data-remove]").on("click", (e) => {
			e.preventDefault();
			const id = e.currentTarget.dataset.remove;
			frappe.confirm(__("Remove this message? The customer will see \"Message removed\"; you keep the text."), () => call("remove_message", { message: id }));
		});
		$m.find("[data-react]").on("click", (e) => call("react", { message: e.currentTarget.dataset.react, emoji: e.currentTarget.dataset.emoji }));
		$m.find("[data-pick]").on("click", (e) => {
			e.preventDefault();
			const id = e.currentTarget.dataset.pick;
			const $bubble = $m.find(`[data-msg="${CSS.escape(id)}"]`);
			$m.find(".txk-picker").remove();
			const set = (c.messaging || {}).reactions || [];
			$bubble.append(`<div class="txk-picker">${set.map((r) => `<button data-emoji="${esc(r)}">${esc(r)}</button>`).join("")}</div>`);
			$bubble.find(".txk-picker button").on("click", (ev) => call("react", { message: id, emoji: ev.currentTarget.dataset.emoji }));
		});
		$m.find("[data-history]").on("click", (e) => {
			e.preventDefault();
			frappe.call({ method: API + "message_history", args: { name: c.name, message: e.currentTarget.dataset.history }, type: "GET" }).then((r) => {
				const rows = (r.message || []).map((h) => `<div style="border-bottom:1px solid var(--border-color);padding:6px 0">
					<div class="small text-muted">${esc(h.edited_by || "")} · ${frappe.datetime.str_to_user(h.edited_on)}</div><div style="white-space:pre-wrap">${esc(h.text)}</div></div>`).join("");
				frappe.msgprint({ title: __("Earlier versions"), message: rows || __("No earlier versions.") });
			});
		});
		// previews: images and voice notes load through the authorised staff download
		$m.find("[data-img], [data-audio]").each((_i, el) => {
			const id = el.dataset.img || el.dataset.audio;
			fetch(`/api/method/thinknxg_support.api.staff.v1.attachment?message=${encodeURIComponent(id)}`, { credentials: "same-origin" })
				.then((res) => (res.ok ? res.blob() : null)).then((b) => { if (b) el.src = URL.createObjectURL(b); });
		});
		$m.find(".txk-attach").on("change", (e) => {
			this.file = e.target.files[0] || null;
			this.voiceSeconds = null;
			e.target.value = "";
			$m.find(".txk-file").prop("hidden", !this.file).find("span").text(this.file ? this.file.name : "");
		});
		$m.find(".txk-filecancel").on("click", (e) => { e.preventDefault(); this.file = null; $m.find(".txk-file").prop("hidden", true); });
		$m.find(".txk-voice").on("click", (e) => this.toggleVoice(c, $(e.currentTarget)));
	}

	// 1.14: priority and tags
	bindOrganise(c) {
		const reload = () => { this.loadThread(true); this.refresh(true); };
		this.$main.find(".txk-priority").on("change", (e) =>
			frappe.call({ method: API + "set_priority", args: { name: c.name, priority: e.target.value } }).then(reload));
		this.$main.find("[data-untag]").on("click", (e) => {
			e.preventDefault();
			frappe.call({ method: API + "set_tags", args: { name: c.name, remove: JSON.stringify([e.currentTarget.dataset.untag]) } }).then(reload);
		});
		this.$main.find(".txk-addtag").on("click", (e) => {
			e.preventDefault();
			frappe.call({ method: API + "tag_suggestions", type: "GET", quiet: true }).then((r) => {
				const d = new frappe.ui.Dialog({ title: __("Add a tag"), fields: [{ fieldname: "tag", fieldtype: "Autocomplete", label: __("Tag"),
					options: (r.message || []).filter((t) => !(c.tags || []).includes(t)), reqd: 1 }],
					primary_action_label: __("Add"),
					primary_action: (v) => { d.hide(); frappe.call({ method: API + "set_tags", args: { name: c.name, add: JSON.stringify([v.tag]) } }).then(reload); } });
				d.show();
			});
		});
	}

	async toggleVoice(c, $btn) {
		if (this.recorder) {
			this.recorder.stop();
			return;
		}
		try {
			const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
			const type = ["audio/ogg;codecs=opus", "audio/webm;codecs=opus", "audio/mp4"].find((x) => MediaRecorder.isTypeSupported(x)) || "";
			const rec = new MediaRecorder(stream, type ? { mimeType: type } : undefined);
			const chunks = [];
			const started = Date.now();
			rec.ondataavailable = (ev) => ev.data && ev.data.size && chunks.push(ev.data);
			rec.onstop = () => {
				stream.getTracks().forEach((t) => t.stop());
				this.recorder = null;
				$btn.removeClass("btn-danger").text("🎤");
				const mime = (rec.mimeType || "audio/webm").split(";")[0];
				const ext = mime.includes("ogg") ? "ogg" : mime.includes("mp4") ? "m4a" : "webm";
				this.file = new File(chunks, `voice-note-${Date.now()}.${ext}`, { type: mime });
				this.voiceSeconds = Math.max(1, Math.round((Date.now() - started) / 1000));
				this.send(c);
			};
			rec.start(250);
			this.recorder = rec;
			$btn.addClass("btn-danger").text(__("Stop and send"));
			const max = ((c.messaging || {}).max_voice_seconds || 120) * 1000;
			setTimeout(() => this.recorder === rec && rec.stop(), max);
		} catch (err) {
			frappe.msgprint(__("Allow the microphone to record a voice note."));
		}
	}

	// ---------------------------------------------------------------- AI copilot (1.10): drafts only
	showInsight(c) {
		const esc = frappe.utils.escape_html;
		frappe.call({ method: COPILOT + "insight", args: { name: c.name }, type: "GET", quiet: true }).then((r) => {
			const i = r.message || {};
			if (this.active !== c.name) return;
			const tone = { Negative: "red", Neutral: "gray", Positive: "green" }[i.sentiment];
			const bits = [];
			if (i.sentiment) bits.push(`<span class="indicator-pill ${tone}">${esc(__(i.sentiment))}</span>`);
			if (i.urgency === "High") bits.push(`<span class="indicator-pill red">${__("Urgent")}</span>`);
			if (i.intent) bits.push(`<span class="indicator-pill blue">${esc(i.intent)}</span>`);
			if (i.customer_language) bits.push(`<span class="indicator-pill gray">${esc(i.customer_language.toUpperCase())}</span>`);
			if (bits.length) this.$main.find(".txk-head h4").after(`<div class="txk-insight" title="${__("AI analysis of the customer's latest message")}">${bits.join(" ")}</div>`);
			this.insight = i;
		});
	}

	copilot(act, c, data) {
		const esc = frappe.utils.escape_html;
		const [kind, opt] = act.split(":");
		const $ta = this.$main.find("textarea");
		const draft = ($ta.val() || "").trim();
		const put = (text) => { $ta.val(text).trigger("focus"); };
		const busy = frappe.show_alert({ message: __("AI is working…"), indicator: "blue" }, 15);
		const done = () => busy && busy.remove && busy.remove();
		const call = (method, args) => frappe.call({ method: COPILOT + method, args: Object.assign({ name: c.name }, args), type: "POST" })
			.then((r) => { done(); return r.message || {}; }, (e) => { done(); throw e; });
		if (kind === "suggest") {
			return call("suggest").then((m) => {
				const items = m.suggestions || [];
				if (!items.length) return frappe.msgprint(__("No suggestion this time."));
				const d = new frappe.ui.Dialog({ title: __("Suggested replies"), fields: [{ fieldtype: "HTML", fieldname: "list" }] });
				d.fields_dict.list.$wrapper.html(items.map((s, i) => `<div class="txk-sug" style="border:1px solid var(--border-color);border-radius:8px;padding:8px 10px;margin-bottom:8px">
					<div class="small text-muted">${esc(s.label)}</div><div style="white-space:pre-wrap">${esc(s.text)}</div>
					<button class="btn btn-default btn-xs" data-use="${i}" style="margin-top:6px">${__("Use this")}</button></div>`).join("")
					+ (m.sources && m.sources.length ? `<div class="small text-muted">${__("Based on")}: ${m.sources.map((x) => esc(x.title)).join(", ")}</div>` : ""));
				d.fields_dict.list.$wrapper.find("[data-use]").on("click", (e) => { put(items[+e.currentTarget.dataset.use].text); d.hide(); });
				d.show();
			});
		}
		if (kind === "rewrite") {
			if (!draft) return frappe.msgprint(__("Write a draft first, then ask the AI to rewrite it."));
			return call("rewrite", { text: draft, style: opt }).then((m) => m.text && put(m.text));
		}
		if (kind === "translate" && opt === "customer") {
			if (!draft) return frappe.msgprint(__("Write a draft first."));
			const target = (this.insight && this.insight.customer_language) || "ar";
			return call("translate", { text: draft, target }).then((m) => m.text && put(m.text));
		}
		if (kind === "translate") {
			const last = (data.messages || []).filter((m) => m.direction === "Inbound").pop();
			if (!last) return frappe.msgprint(__("The customer has not written yet."));
			const text = $("<div>").html(last.content || "").text();
			return call("translate", { text, target: (frappe.boot.lang || "en").slice(0, 2) })
				.then((m) => frappe.msgprint({ title: __("Customer's last message, translated"), message: `<div style="white-space:pre-wrap">${esc(m.text || "")}</div>` }));
		}
		if (kind === "summarize") {
			return call("summarize").then((m) => frappe.msgprint({ title: __("Conversation summary"), message: `<div style="white-space:pre-wrap">${esc(m.summary || "")}</div>` }));
		}
		if (kind === "recommend") {
			return call("recommend").then((m) => {
				const arts = (m.articles || []).map((a) => `<li>${a.route && /^(https?:)?\//.test(a.route) ? `<a href="${esc(a.route)}" target="_blank">${esc(a.title)}</a>` : esc(a.title)}${a.used ? " ✓" : ""}</li>`).join("");
				const fu = (m.follow_ups || []).map((q) => `<li>${esc(q)}</li>`).join("");
				frappe.msgprint({ title: __("Recommended"), wide: true, message:
					`<p style="white-space:pre-wrap">${esc(m.solution || __("No recommendation from the knowledge base."))}</p>`
					+ (fu ? `<h5>${__("Questions to ask")}</h5><ul>${fu}</ul>` : "")
					+ (arts ? `<h5>${__("Knowledge base")}</h5><ul>${arts}</ul>` : "") });
			});
		}
		if (kind === "note") {
			return call("note").then(() => { frappe.show_alert({ message: __("Summary added as an internal note"), indicator: "green" }); this.loadThread(true); });
		}
	}

	send(c) {
		const $ta = this.$main.find("textarea");
		const text = ($ta.val() || "").trim();
		const file = this.file;
		if (!text && !file) return;
		const go = () => {
			const html = text.split(/\n{2,}/).map((p) => `<p>${frappe.utils.escape_html(p).replace(/\n/g, "<br>")}</p>`).join("");
			$ta.val("").prop("disabled", true);
			const args = { name: this.active, content: html, internal: this.internal, reply_to: this.replyTo || "",
				voice_seconds: file && this.voiceSeconds ? this.voiceSeconds : "" };
			const done = () => { this.replyTo = null; this.file = null; this.voiceSeconds = null; this.loadThread(true); };
			const request = file ? this.upload(args, file) : frappe.call({ method: API + "reply", args });
			Promise.resolve(request)
				.then(done)
				.catch(() => $ta.val(text))
				.finally(() => $ta.prop("disabled", false).trigger("focus"));
		};
		if (!this.internal && c.handling === "Bot") {
			frappe.call({ method: API + "take_over", args: { name: c.name } }).then(go);
		} else go();
	}

	upload(args, file) {
		const fd = new FormData();
		Object.entries(args).forEach(([k, v]) => v !== "" && v != null && fd.append(k, v));
		fd.append("file", file, file.name);
		return fetch(`/api/method/${API}reply`, { method: "POST", body: fd, credentials: "same-origin",
			headers: { "X-Frappe-CSRF-Token": frappe.csrf_token, Accept: "application/json" } })
			.then(async (res) => {
				if (!res.ok) {
					const body = await res.json().catch(() => ({}));
					frappe.msgprint(JSON.parse(body._server_messages || "[]").map((m) => JSON.parse(m).message).join("<br>") || __("The file could not be sent."));
					throw new Error("upload failed");
				}
			});
	}

	// ---------------------------------------------------------------- canned responses
	loadCanned(c) {
		if (this.canned && this.cannedChannel === c.channel) return Promise.resolve(this.canned);
		return frappe.call({ method: TOOLS + "canned_responses", args: { channel: c.channel || "Portal" }, type: "GET" })
			.then((r) => { this.canned = r.message || []; this.cannedChannel = c.channel; return this.canned; });
	}

	insertCanned(row, c) {
		const $ta = this.$main.find("textarea");
		const text = cannedText(row.content, c);
		const cur = $ta.val() || "";
		$ta.val(/^\/\S*$/.test(cur.trim()) || !cur.trim() ? text : cur.replace(/\s*$/, "\n\n") + text).trigger("focus");
		$ta[0].setSelectionRange($ta.val().length, $ta.val().length);
		this.$main.find(".txk-suggest").prop("hidden", true);
		frappe.call({ method: TOOLS + "canned_used", args: { name: row.name }, type: "POST", quiet: true });
	}

	// Typing /word at the start of the box lists matching canned responses (arrows + Enter or Tab to pick).
	suggest($ta, c) {
		const $box = this.$main.find(".txk-suggest");
		const m = /^\/(\S*)$/.exec(($ta.val() || "").trim());
		if (!m) { $box.prop("hidden", true); this.suggestions = null; return; }
		this.loadCanned(c).then((rows) => {
			const q = m[1].toLowerCase();
			this.suggestions = rows.filter((r) => !q || (r.shortcut || "").startsWith(q) || (r.title || "").toLowerCase().includes(q)).slice(0, 8);
			this.suggestIndex = 0;
			const esc = frappe.utils.escape_html;
			$box.html(this.suggestions.map((r, i) => `<button type="button" data-i="${i}" class="${i === 0 ? "on" : ""}">
				${r.shortcut ? `<b>/${esc(r.shortcut)}</b>` : ""}${esc(r.title)} <span class="text-muted">· ${esc(r.category || "")}</span></button>`).join("")
				|| `<div class="text-muted small" style="padding:8px 10px">${__("No canned response matches")}</div>`).prop("hidden", false);
			$box.find("button").on("mousedown", (e) => { e.preventDefault(); this.insertCanned(this.suggestions[+e.currentTarget.dataset.i], c); });
		});
	}

	suggestKeys(e, c) {
		const $box = this.$main.find(".txk-suggest");
		if ($box.prop("hidden") || !this.suggestions || !this.suggestions.length) return false;
		if (e.key === "ArrowDown" || e.key === "ArrowUp") {
			e.preventDefault();
			this.suggestIndex = (this.suggestIndex + (e.key === "ArrowDown" ? 1 : -1) + this.suggestions.length) % this.suggestions.length;
			$box.find("button").removeClass("on").eq(this.suggestIndex).addClass("on");
			return true;
		}
		if (e.key === "Enter" || e.key === "Tab") { e.preventDefault(); this.insertCanned(this.suggestions[this.suggestIndex], c); return true; }
		if (e.key === "Escape") { $box.prop("hidden", true); return true; }
		return false;
	}

	cannedDialog(c) {
		this.loadCanned(c).then((rows) => {
			const esc = frappe.utils.escape_html;
			const cats = [...new Set(rows.map((r) => r.category).filter(Boolean))].sort();
			const d = new frappe.ui.Dialog({
				title: __("Canned responses"), size: "large",
				fields: [
					{ fieldname: "q", fieldtype: "Data", label: __("Search"), placeholder: __("Title, shortcut or text") },
					{ fieldname: "cb", fieldtype: "Column Break" },
					{ fieldname: "cat", fieldtype: "Select", label: __("Category"), options: ["", ...cats] },
					{ fieldname: "sb", fieldtype: "Section Break" },
					{ fieldname: "list", fieldtype: "HTML" },
				],
				secondary_action_label: __("Manage canned responses"),
				secondary_action: () => { d.hide(); frappe.set_route("List", "Support Canned Response"); },
			});
			const render = () => {
				const q = (d.get_value("q") || "").toLowerCase(), cat = d.get_value("cat");
				const list = rows.filter((r) => (!cat || r.category === cat) && (!q || (r.title || "").toLowerCase().includes(q)
					|| (r.shortcut || "").includes(q) || cannedText(r.content, c).toLowerCase().includes(q)));
				d.fields_dict.list.$wrapper.html(list.length ? list.map((r, i) => `
					<div class="txk-cr" data-i="${rows.indexOf(r)}" style="border:1px solid var(--border-color);border-radius:8px;padding:8px 10px;margin-bottom:8px;cursor:pointer">
						<div><b>${esc(r.title)}</b> ${r.shortcut ? `<code>/${esc(r.shortcut)}</code>` : ""}
						<span class="text-muted small">· ${esc(r.category || __("Uncategorised"))}${r.visibility === "Only Me" ? " · " + __("Only me") : ""}</span></div>
						<div class="text-muted small" style="white-space:pre-wrap;max-height:4.5em;overflow:hidden">${esc(cannedText(r.content, c))}</div>
					</div>`).join("") : `<p class="text-muted">${__("No canned responses yet.")}</p>`);
				d.fields_dict.list.$wrapper.find(".txk-cr").on("click", (e) => { d.hide(); this.insertCanned(rows[+e.currentTarget.dataset.i], c); });
			};
			d.fields_dict.q.$input.on("input", render);
			d.fields_dict.cat.$input.on("change", render);
			render();
			d.show();
			setTimeout(() => d.fields_dict.q.$input.trigger("focus"), 200);
		});
	}

	// ---------------------------------------------------------------- end chat with wrap-up
	endChat(c, done) {
		frappe.call({ method: TOOLS + "closing_form", type: "GET" }).then((r) => {
			const f = r.message || { reasons: [], questions: [] };
			const fields = [];
			if (f.reasons.length) fields.push({ fieldname: "reason", fieldtype: "Select", label: __("Why is the chat ending?"),
				options: ["", ...f.reasons], reqd: f.require_reason ? 1 : 0 });
			f.questions.forEach((q) => {
				const fn = "q_" + q.idx;
				if (q.answer_type === "Yes/No") fields.push({ fieldname: fn, fieldtype: "Select", label: q.question, options: ["", __("Yes"), __("No")], reqd: q.required });
				else if (q.answer_type === "Choice") fields.push({ fieldname: fn, fieldtype: "Select", label: q.question, options: ["", ...q.options], reqd: q.required });
				else if (q.answer_type === "Rating") fields.push({ fieldname: fn, fieldtype: "Rating", label: q.question, reqd: q.required });
				else fields.push({ fieldname: fn, fieldtype: "Small Text", label: q.question, reqd: q.required });
			});
			fields.push({ fieldname: "notes", fieldtype: "Small Text", label: __("Notes for the team"),
				description: __("Saved with the chat history. The customer does not see them.") });
			if (f.closing_message && c.status !== "Closed") {
				fields.push({ fieldname: "send_closing_message", fieldtype: "Check", default: 1,
					label: __("Send the closing message"), description: frappe.utils.escape_html(f.closing_message) });
			}
			const d = new frappe.ui.Dialog({
				title: __("End chat"), fields,
				primary_action_label: __("End chat"),
				primary_action: (v) => {
					const answers = {};
					f.questions.forEach((q) => {
						let a = v["q_" + q.idx];
						if (q.answer_type === "Rating" && a) a = String(Math.round(a * 5));
						if (a) answers[q.idx] = a;
					});
					frappe.call({ method: TOOLS + "end_chat", type: "POST", freeze: true, args: { name: c.name, reason: v.reason,
						notes: v.notes, answers: JSON.stringify(answers), send_closing_message: v.send_closing_message ? 1 : 0 } })
						.then(() => { d.hide(); frappe.show_alert({ message: __("Chat ended"), indicator: "green" }); done(); });
				},
			});
			d.show();
		});
	}

	action(act, c) {
		const name = c.name;
		const reload = () => { this.loadThread(true); this.refresh(true); };
		if (act === "assign") frappe.call({ method: API + "assign", args: { name } }).then(reload);
		if (act === "takeover") frappe.call({ method: API + "take_over", args: { name } }).then(reload);
		if (act === "tobot") frappe.call({ method: API + "return_to_assistant", args: { name } }).then(reload);
		if (act === "close") this.endChat(c, reload);
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
