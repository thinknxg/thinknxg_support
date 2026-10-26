<template>
	<div v-if="visible" class="txc-root" :class="rootClass" :dir="dir" :lang="lang"
		:style="{ '--txc-brand': cfg.brand.color }">
		<button v-if="!inline && !open" type="button" class="txc-launcher" :aria-label="t('launcher')" @click="setOpen(true)">
			<svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><path fill="currentColor"
				d="M12 3C6.5 3 2 6.9 2 11.7c0 2.3 1 4.4 2.8 6L4 21l3.9-1.6c1.2.4 2.6.7 4.1.7 5.5 0 10-3.9 10-8.7S17.5 3 12 3z" /></svg>
			<span class="txc-launcher__label">{{ cfg.title || t("launcher") }}</span>
			<span v-if="unread" class="txc-unread" :aria-label="unread + ' ' + t('unread')">{{ unread }}</span>
		</button>

		<section v-if="open || inline" class="txc-panel" role="dialog" :aria-label="cfg.title" aria-live="polite">
			<header class="txc-head">
				<img :src="cfg.brand.logo" alt="" class="txc-logo" />
				<div class="txc-head__text">
					<strong>{{ cfg.title || t("launcher") }}</strong>
					<small><span class="txc-dot" :class="{ on: cfg.online }"></span>{{ cfg.online ? t("online_hint") : t("offline") }}</small>
				</div>
				<a v-if="cfg.whatsapp_url" :href="cfg.whatsapp_url" target="_blank" rel="noopener" class="txc-iconbtn txc-wa"
					:title="t('whatsapp')" :aria-label="t('whatsapp')">
					<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path fill="currentColor" d="M12 2a10 10 0 0 0-8.6 15.1L2 22l5-1.3A10 10 0 1 0 12 2zm0 18.2c-1.5 0-3-.4-4.3-1.2l-.3-.2-3 .8.8-2.9-.2-.3A8.2 8.2 0 1 1 12 20.2zm4.5-6.1c-.2-.1-1.5-.7-1.7-.8s-.4-.1-.6.1-.6.8-.8 1-.3.2-.5.1a6.7 6.7 0 0 1-3.3-2.9c-.3-.4.3-.4.7-1.4.1-.2 0-.3 0-.4l-.8-1.8c-.2-.5-.4-.4-.6-.4h-.5a1 1 0 0 0-.7.3 3 3 0 0 0-.9 2.2 5.2 5.2 0 0 0 1.1 2.8 11.9 11.9 0 0 0 4.6 4c1.7.7 2.3.8 3.2.7.5-.1 1.5-.6 1.8-1.2s.2-1.1.1-1.2-.2-.1-.4-.2z" /></svg>
				</a>
				<button v-if="phase === 'chat' && hasChat" type="button" class="txc-iconbtn" :title="t('end')" :aria-label="t('end')"
					@click="confirmEnd = true">
					<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="2"
						stroke-linecap="round" d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9" /></svg>
				</button>
				<button v-if="!inline" type="button" class="txc-iconbtn" :aria-label="t('close')" @click="setOpen(false)">
					<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="2"
						stroke-linecap="round" d="M6 9l6 6 6-6" /></svg>
				</button>
			</header>

			<div ref="scroller" class="txc-body">
				<div v-if="phase === 'loading'" class="txc-center"><span class="txc-spin"></span></div>

				<div v-else-if="phase === 'login'" class="txc-center txc-stack">
					<p>{{ t("login") }}</p>
					<a class="txc-btn" :href="loginUrl">{{ t("login_btn") }}</a>
					<template v-if="cfg.whatsapp_url">
						<span class="txc-muted">{{ t("or") }}</span>
						<a class="txc-btn txc-btn--wa" :href="cfg.whatsapp_url" target="_blank" rel="noopener">{{ t("whatsapp") }}</a>
					</template>
				</div>

				<div v-else-if="phase === 'whatsapp'" class="txc-center txc-stack">
					<p>{{ cfg.greeting }}</p>
					<a class="txc-btn txc-btn--wa" :href="cfg.whatsapp_url" target="_blank" rel="noopener">{{ t("whatsapp") }}</a>
				</div>

				<template v-else>
					<div class="txc-msg txc-msg--them"><div class="txc-bubble">{{ cfg.greeting }}</div></div>
					<p v-if="!cfg.online && cfg.offline_message" class="txc-note">{{ cfg.offline_message }}</p>

					<form v-if="phase === 'prechat'" class="txc-form" @submit.prevent="startGuest">
						<label><span>{{ t("name") }}</span>
							<input id="txc-name" v-model.trim="form.name" required maxlength="80" autocomplete="name" :readonly="cfg.prefill.locked" /></label>
						<label><span>{{ t("email") }}</span>
							<input id="txc-email" v-model.trim="form.email" type="email" required autocomplete="email" :readonly="cfg.prefill.locked" /></label>
						<label><span>{{ t("phone") }} <em>({{ t("optional") }})</em></span>
							<input id="txc-phone" v-model.trim="form.phone" type="tel" maxlength="20" autocomplete="tel" dir="ltr" /></label>
						<label><span>{{ t("message") }}</span>
							<textarea id="txc-first" v-model="form.message" rows="3" required :maxlength="cfg.max_length"></textarea></label>
						<input v-model="form.website" class="txc-hp" tabindex="-1" autocomplete="off" aria-hidden="true" name="website" />
						<p v-if="error" class="txc-error" role="alert">{{ error }}</p>
						<button class="txc-btn" :disabled="busy">{{ busy ? t("sending") : t("start") }}</button>
						<p v-if="cfg.privacy_note" class="txc-muted txc-small">{{ cfg.privacy_note }}</p>
					</form>

					<template v-else>
						<div v-for="m in messages" :key="m.id" class="txc-msg" :class="m.from_customer ? 'txc-msg--me' : 'txc-msg--them'">
							<small v-if="!m.from_customer" class="txc-author">{{ m.author || t("support") }}</small>
							<div class="txc-bubble" v-html="m.content"></div>
							<small class="txc-time">{{ time(m.created) }}</small>
						</div>
						<div v-for="p in pending" :key="p.cid" class="txc-msg txc-msg--me">
							<button v-if="p.failed" type="button" class="txc-bubble txc-bubble--failed" @click="retry(p)">
								{{ p.text }}<small>{{ t("failed") }}</small></button>
							<div v-else class="txc-bubble txc-bubble--pending">{{ p.text }}</div>
						</div>
						<p v-if="mode === 'guest' && phase === 'chat' && !agentReplied" class="txc-note">{{ t("email_hint") }}</p>
						<div v-if="phase === 'ended'" class="txc-ended">
							<p>{{ expired ? t("expired") : t("ended") }}</p>
							<template v-if="!expired && !rated">
								<p class="txc-muted">{{ t("rate") }}</p>
								<div class="txc-stars">
									<button v-for="n in 5" :key="n" type="button" :aria-label="n + '/5'" @click="rate(n)">★</button>
								</div>
							</template>
							<p v-else-if="rated" class="txc-muted">{{ t("thanks") }}</p>
							<button type="button" class="txc-btn" @click="newChat">{{ t("new_chat") }}</button>
						</div>
					</template>
				</template>
			</div>

			<footer v-if="phase === 'chat'" class="txc-foot">
				<div v-if="confirmEnd" class="txc-confirm">
					<span>{{ t("end_confirm") }}</span>
					<button type="button" class="txc-btn txc-btn--ghost" @click="confirmEnd = false">{{ t("no") }}</button>
					<button type="button" class="txc-btn" @click="endChat">{{ t("yes") }}</button>
				</div>
				<form v-else class="txc-compose" @submit.prevent="send">
					<label v-if="mode === 'customer'" class="txc-iconbtn" :title="t('attach')">
						<input type="file" hidden @change="pickFile" />
						<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="2"
							stroke-linecap="round" d="M21.4 11.1l-9.2 9.2a6 6 0 0 1-8.5-8.5l9.2-9.2a4 4 0 0 1 5.7 5.7l-9.2 9.2a2 2 0 0 1-2.8-2.8l8.5-8.5" /></svg>
					</label>
					<div class="txc-compose__input">
						<span v-if="file" class="txc-chip">{{ file.name }} <button type="button" @click="file = null">×</button></span>
						<textarea id="txc-draft" v-model="draft" rows="1" :placeholder="t('type')" :maxlength="cfg.max_length"
							:aria-label="t('type')" @keydown.enter.exact.prevent="send"></textarea>
					</div>
					<button class="txc-send" :disabled="!draft.trim() && !file" :aria-label="t('send')">
						<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path fill="currentColor" d="M3 20l18-8L3 4v6l12 2-12 2z" /></svg>
					</button>
				</form>
			</footer>
		</section>
	</div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import { ChatError, chatCall, newId, session, textToHtml } from "./client";
import { STRINGS } from "./strings";

const props = defineProps({
	inline: { type: Boolean, default: false },
	context: { type: String, default: "website" }, // website | portal | page
	organization: { type: String, default: null },
	lang: { type: String, default: null },
});

const cfg = ref(null);
const open = ref(false);
const phase = ref("loading"); // loading | login | whatsapp | prechat | chat | ended
const messages = ref([]);
const pending = ref([]);
const draft = ref("");
const file = ref(null);
const busy = ref(false);
const error = ref("");
const confirmEnd = ref(false);
const rated = ref(false);
const expired = ref(false);
const unread = ref(0);
const scroller = ref(null);
const form = reactive({ name: "", email: "", phone: "", message: "", website: "" });
let seenAgent = 0;
let timer = null;
let conversation = null;

const OPEN_KEY = "thinknxg_support:chat-open";
const mode = computed(() => cfg.value?.mode);
const lang = computed(() => props.lang || cfg.value?.lang || document.documentElement.lang || "en");
const dir = computed(() => (lang.value === "ar" ? "rtl" : "ltr"));
const hasChat = computed(() => !!conversation || messages.value.length > 0);
const agentReplied = computed(() => messages.value.some((m) => !m.from_customer));
const loginUrl = computed(() => "/login?redirect-to=" + encodeURIComponent(window.location.pathname));
const visible = computed(() => {
	const c = cfg.value;
	if (!c || !c.enabled || c.mode === "staff") return false;
	if (props.context === "website" && !c.show_on_website) return false;
	return true;
});
const rootClass = computed(() => ({
	"txc-root--inline": props.inline,
	"txc-root--left": cfg.value?.position === "left",
	"txc-root--open": open.value,
}));

function t(key) {
	return (STRINGS[lang.value] || STRINGS.en)[key] || STRINGS.en[key] || key;
}

function time(v) {
	if (!v) return "";
	const d = new Date(String(v).replace(" ", "T"));
	if (isNaN(d)) return "";
	return new Intl.DateTimeFormat(lang.value === "ar" ? "ar-OM" : "en-GB", { hour: "2-digit", minute: "2-digit" }).format(d);
}

function scrollDown() {
	nextTick(() => scroller.value && (scroller.value.scrollTop = scroller.value.scrollHeight));
}

function setOpen(v) {
	open.value = v;
	try {
		window.sessionStorage.setItem(OPEN_KEY, v ? "1" : "0");
	} catch (e) {
		/* ignore */
	}
	if (v) {
		unread.value = 0;
		seenAgent = messages.value.filter((m) => !m.from_customer).length;
		refresh();
		scrollDown();
	}
	schedule();
}

function applyMessages(list, status) {
	const before = messages.value.length;
	messages.value = list || [];
	const agentCount = messages.value.filter((m) => !m.from_customer).length;
	if (open.value || props.inline) seenAgent = agentCount;
	else unread.value = Math.max(0, agentCount - seenAgent);
	if (status === "Closed") {
		phase.value = "ended";
		rated.value = rated.value || false;
	}
	if (messages.value.length !== before) scrollDown();
}

async function refresh() {
	if (!cfg.value || !["chat", "ended"].includes(phase.value) || phase.value === "ended" && expired.value) return;
	try {
		if (mode.value === "customer") {
			const r = await chatCall("my_chat", { organization: props.organization });
			conversation = r.conversation;
			applyMessages(r.messages, r.status);
		} else {
			const s = session.get();
			if (!s) return;
			const r = await chatCall("messages", { conversation: s.conversation }, { token: s.token });
			conversation = r.conversation;
			rated.value = r.rated;
			applyMessages(r.messages, r.status);
		}
	} catch (e) {
		if (e instanceof ChatError && e.status === 403 && mode.value !== "customer") {
			session.clear();
			expired.value = true;
			phase.value = "ended";
		}
	}
}

function schedule() {
	clearTimeout(timer);
	if (!cfg.value || !["chat", "ended"].includes(phase.value) || phase.value === "ended") return;
	const active = open.value || props.inline;
	timer = setTimeout(async () => {
		if (!document.hidden) await refresh();
		schedule();
	}, active ? 4000 : 30000);
}

async function startGuest() {
	busy.value = true;
	error.value = "";
	const cid = newId();
	try {
		const r = await chatCall("start", {
			name: form.name, email: form.email, phone: form.phone, message: textToHtml(form.message),
			page: window.location.pathname, client_message_id: cid, website: form.website,
		}, { post: true });
		session.set({ conversation: r.conversation, token: r.token });
		form.message = "";
		phase.value = "chat";
		await refresh();
		schedule();
	} catch (e) {
		error.value = e.status === 0 ? t("network") : e.message;
	} finally {
		busy.value = false;
	}
}

async function deliver(p) {
	p.failed = false;
	try {
		if (mode.value === "customer") {
			await chatCall("customer_send", { message: textToHtml(p.text), organization: props.organization, client_message_id: p.cid },
				{ post: true, files: p.file ? [p.file] : [] });
		} else {
			const s = session.get();
			await chatCall("send", { conversation: s.conversation, message: textToHtml(p.text), client_message_id: p.cid },
				{ post: true, token: s.token });
		}
		pending.value = pending.value.filter((x) => x.cid !== p.cid);
		await refresh();
		schedule();
	} catch (e) {
		p.failed = true;
		if (e instanceof ChatError && e.status === 403 && mode.value !== "customer") {
			pending.value = [];
			session.clear();
			expired.value = true;
			phase.value = "ended";
		}
	}
}

function send() {
	const text = draft.value.trim();
	if (!text && !file.value) return;
	const p = reactive({ cid: newId(), text: text || (file.value && file.value.name), file: file.value, failed: false });
	pending.value.push(p);
	draft.value = "";
	file.value = null;
	scrollDown();
	deliver(p);
}

function retry(p) {
	deliver(p);
}

function pickFile(e) {
	file.value = (e.target.files || [])[0] || null;
	e.target.value = "";
}

async function endChat() {
	confirmEnd.value = false;
	try {
		if (mode.value === "customer") await chatCall("customer_end", { organization: props.organization }, { post: true });
		else {
			const s = session.get();
			if (s) await chatCall("end", { conversation: s.conversation }, { post: true, token: s.token });
		}
	} catch (e) {
		/* closing is best effort */
	}
	phase.value = "ended";
	clearTimeout(timer);
}

async function rate(n) {
	rated.value = true;
	try {
		if (mode.value === "customer") await chatCall("customer_end", { organization: props.organization, rating: n }, { post: true });
		else {
			const s = session.get();
			if (s) await chatCall("end", { conversation: s.conversation, rating: n }, { post: true, token: s.token });
		}
	} catch (e) {
		/* ignore */
	}
}

function newChat() {
	messages.value = [];
	pending.value = [];
	conversation = null;
	expired.value = false;
	rated.value = false;
	if (mode.value === "customer") phase.value = "chat";
	else {
		session.clear();
		phase.value = "prechat";
	}
	schedule();
}

async function init() {
	try {
		cfg.value = await chatCall("config", { context_name: props.context });
	} catch (e) {
		cfg.value = null;
		return;
	}
	const c = cfg.value;
	if (c.prefill && c.prefill.name) {
		form.name = c.prefill.name;
		form.email = c.prefill.email || "";
	}
	if (c.mode === "off") phase.value = c.whatsapp_url ? "whatsapp" : "loading";
	else if (c.mode === "login") phase.value = "login";
	else if (c.mode === "customer") {
		phase.value = "chat";
		await refresh();
	} else if (c.mode === "guest") {
		if (session.get()) {
			phase.value = "chat";
			await refresh();
		} else phase.value = "prechat";
	}
	try {
		if (!props.inline && window.sessionStorage.getItem(OPEN_KEY) === "1") open.value = true;
	} catch (e) {
		/* ignore */
	}
	if (open.value || props.inline) seenAgent = messages.value.filter((m) => !m.from_customer).length;
	schedule();
	scrollDown();
}

watch(() => props.organization, (v, old) => {
	if (v && old && v !== old && mode.value === "customer") {
		messages.value = [];
		phase.value = "chat";
		refresh();
	}
});

onMounted(() => {
	init();
	document.addEventListener("visibilitychange", onVisible);
});
onBeforeUnmount(() => {
	clearTimeout(timer);
	document.removeEventListener("visibilitychange", onVisible);
});
function onVisible() {
	if (!document.hidden) refresh();
}
</script>
