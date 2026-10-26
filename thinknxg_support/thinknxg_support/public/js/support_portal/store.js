import { reactive } from "vue";
import { translate } from "./i18n";

const boot = window.thinknxg_support_boot || {};
const ORG_KEY = "thinknxg_support:org";

function readOrg() {
	try {
		return window.localStorage.getItem(ORG_KEY);
	} catch (e) {
		return null;
	}
}

export const state = reactive({
	csrf: boot.csrf_token,
	base: boot.base || "/thinkdesk",
	lang: boot.lang || "en",
	ready: false,
	linked: true,
	unlinkedMessage: "",
	user: null,
	orgs: [],
	org: null,
	modules: {},
	branding: {},
	adminWarnings: [],
	provider: "Portal Native",
	agentUrl: null,
	maxMb: 10,
	extensions: "",
	unreadNotifications: 0,
	unreadMessages: 0,
	toast: null,
	t(key, vars) {
		return translate(state.lang, key, vars);
	},
});

export function currentOrg() {
	return state.orgs.find((o) => o.customer === state.org) || null;
}

export function can(capability) {
	const o = currentOrg();
	return !!(o && o.capabilities.includes(capability));
}

export function setOrg(customer) {
	state.org = customer;
	try {
		window.localStorage.setItem(ORG_KEY, customer);
	} catch (e) {
		/* storage unavailable */
	}
}

export function applyBoot(data) {
	state.linked = data.linked !== false;
	state.unlinkedMessage = data.message || "";
	state.branding = data.branding || {};
	state.user = data.user && typeof data.user === "object" ? data.user : null;
	state.orgs = data.organizations || [];
	state.modules = data.modules || {};
	state.adminWarnings = data.admin_warnings || [];
	state.provider = data.messaging_provider || "Portal Native";
	state.agentUrl = data.helpdesk_agent_url;
	state.maxMb = data.max_attachment_mb || 10;
	state.extensions = data.allowed_extensions || "";
	if (data.language) setLang(data.language);
	if (data.theme) document.documentElement.dataset.theme = String(data.theme).toLowerCase();
	const stored = readOrg();
	const valid = (c) => state.orgs.some((o) => o.customer === c);
	state.org = valid(stored) ? stored : valid(data.default_organization) ? data.default_organization : state.orgs[0]?.customer || null;
	if (state.branding.primary_color) document.documentElement.style.setProperty("--brand", state.branding.primary_color);
	state.ready = true;
}

export function setLang(lang) {
	state.lang = lang === "ar" ? "ar" : "en";
	document.documentElement.lang = state.lang;
	document.documentElement.dir = state.lang === "ar" ? "rtl" : "ltr";
}

let toastTimer;
export function toast(message, kind = "success") {
	state.toast = { message, kind };
	clearTimeout(toastTimer);
	toastTimer = setTimeout(() => (state.toast = null), 4000);
}

export function fmtDate(value, withTime = false) {
	if (!value) return "";
	const d = new Date(String(value).replace(" ", "T"));
	if (isNaN(d)) return value;
	const opts = withTime ? { dateStyle: "medium", timeStyle: "short" } : { dateStyle: "medium" };
	return new Intl.DateTimeFormat(state.lang === "ar" ? "ar-OM" : "en-GB", opts).format(d);
}

export function fmtMoney(value, currency) {
	const n = Number(value || 0);
	try {
		return new Intl.NumberFormat(state.lang === "ar" ? "ar-OM" : "en-GB", {
			style: "currency", currency: currency || "OMR", minimumFractionDigits: currency === "OMR" ? 3 : 2,
		}).format(n);
	} catch (e) {
		return `${n.toFixed(2)} ${currency || ""}`;
	}
}

export function fmtSize(bytes) {
	const b = Number(bytes || 0);
	if (b < 1024) return `${b} B`;
	if (b < 1024 * 1024) return `${(b / 1024).toFixed(0)} KB`;
	return `${(b / 1024 / 1024).toFixed(1)} MB`;
}
