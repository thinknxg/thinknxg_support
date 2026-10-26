<template>
	<div v-if="!state.ready" class="tx-boot">
		<Loader :loading="!bootError" :error="bootError" @retry="load" />
	</div>

	<div v-else-if="!state.linked" class="tx-unlinked">
		<div class="tx-card tx-unlinked__card">
			<img :src="state.branding.logo" alt="" class="tx-unlinked__logo" />
			<h1>{{ state.t("errors.unlinked") }}</h1>
			<p>{{ state.t("errors.unlinked_help") }}</p>
			<p v-if="state.branding.support_email">
				<a :href="'mailto:' + state.branding.support_email">{{ state.branding.support_email }}</a>
			</p>
			<a class="tx-btn tx-btn--ghost" href="/?cmd=web_logout">{{ state.t("nav.logout") }}</a>
		</div>
	</div>

	<div v-else class="tx-shell" :class="{ 'tx-shell--nav-open': navOpen }">
		<header class="tx-header">
			<button class="tx-iconbtn tx-header__menu" :aria-label="state.t('nav.dashboard')" @click="navOpen = !navOpen">
				<Icon :name="navOpen ? 'x' : 'menu'" />
			</button>
			<a :href="link('')" data-nav class="tx-brand">
				<img :src="state.branding.logo" alt="" />
				<span>{{ state.branding.title }}</span>
			</a>

			<div class="tx-header__spacer"></div>

			<label v-if="state.orgs.length > 1" class="tx-orgswitch">
				<Icon name="building" size="16" />
				<span class="tx-sr">{{ state.t("nav.organization") }}</span>
				<select :value="state.org" @change="switchOrg($event.target.value)">
					<option v-for="o in state.orgs" :key="o.customer" :value="o.customer">{{ o.customer_name }}</option>
				</select>
			</label>
			<span v-else-if="state.orgs.length === 1" class="tx-orgswitch tx-orgswitch--static">
				<Icon name="building" size="16" />{{ state.orgs[0].customer_name }}
			</span>

			<div class="tx-pop">
				<button class="tx-iconbtn" :aria-label="state.t('nav.notifications')" @click="toggleBell">
					<Icon name="bell" />
					<span v-if="state.unreadNotifications" class="tx-dot">{{ state.unreadNotifications > 9 ? "9+" : state.unreadNotifications }}</span>
				</button>
				<div v-if="bellOpen" class="tx-pop__panel tx-notifs" @click.stop>
					<div class="tx-pop__head">
						<strong>{{ state.t("nav.notifications") }}</strong>
						<button class="tx-link" @click="markAll">{{ state.t("common.markAllRead") }}</button>
					</div>
					<p v-if="!notifications.length" class="tx-muted tx-pad">{{ state.t("common.none") }}</p>
					<a v-for="n in notifications" :key="n.name" :href="notifLink(n)" data-nav
						class="tx-notif" :class="{ 'tx-notif--unread': !n.read }" @click="openNotif(n)">
						<span>{{ n.subject }}</span>
						<small>{{ fmtDate(n.creation, true) }}</small>
					</a>
				</div>
			</div>

			<div class="tx-pop">
				<button class="tx-avatar" :aria-label="state.user?.full_name" @click="menuOpen = !menuOpen">
					{{ initials }}
				</button>
				<div v-if="menuOpen" class="tx-pop__panel tx-menu" @click="menuOpen = false">
					<div class="tx-menu__who">
						<strong>{{ state.user?.full_name }}</strong>
						<small>{{ state.user?.email }}</small>
					</div>
					<a :href="link('settings')" data-nav><Icon name="settings" size="16" />{{ state.t("nav.settings") }}</a>
					<a v-if="state.agentUrl" :href="state.agentUrl"><Icon name="headset" size="16" />{{ state.t("nav.agent") }}</a>
					<a href="/?cmd=web_logout"><Icon name="logout" size="16" />{{ state.t("nav.logout") }}</a>
				</div>
			</div>
		</header>

		<nav class="tx-nav" :aria-label="state.branding.title" @click="navOpen = false">
			<a v-for="item in navItems" :key="item.name" :href="link(item.path)" data-nav
				class="tx-nav__item" :class="{ 'tx-nav__item--active': isActive(item) }"
				:aria-current="isActive(item) ? 'page' : null">
				<Icon :name="item.icon" />
				<span>{{ state.t(item.label) }}</span>
				<span v-if="item.name === 'conversations' && state.unreadMessages" class="tx-count">{{ state.unreadMessages }}</span>
			</a>
			<div class="tx-nav__foot">
				<span v-if="state.branding.support_email">{{ state.branding.support_email }}</span>
				<span v-if="state.branding.support_phone" dir="ltr">{{ state.branding.support_phone }}</span>
			</div>
		</nav>
		<div class="tx-scrim" @click="navOpen = false"></div>

		<main class="tx-main" @click="closePops">
			<div v-if="state.adminWarnings.length" class="tx-admin" role="status">
				<Icon name="alert" />
				<div>
					<strong>{{ state.t("admin.warnings") }}</strong>
					<ul><li v-for="w in state.adminWarnings" :key="w">{{ w }}</li></ul>
					<a href="/app/support-portal-settings">{{ state.t("admin.settings") }}</a>
				</div>
			</div>
			<component :is="view" :key="viewKey" />
			<footer v-if="state.branding.footer_text" class="tx-footer">{{ state.branding.footer_text }}</footer>
		</main>

		<div v-if="state.toast" class="tx-toast" :class="'tx-toast--' + state.toast.kind" role="status">
			{{ state.toast.message }}
		</div>

		<ChatWidget context="portal" :organization="state.org" :lang="state.lang" />
	</div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { call } from "./api";
import { route, link, navigate } from "./router";
import { state, applyBoot, setOrg, fmtDate, can } from "./store";
import Icon from "./components/Icon.vue";
import { Loader } from "./components/ui";
import ChatWidget from "../support_chat/ChatWidget.vue";

import Dashboard from "./views/Dashboard.vue";
import Tickets from "./views/Tickets.vue";
import TicketDetail from "./views/TicketDetail.vue";
import NewTicket from "./views/NewTicket.vue";
import Conversations from "./views/Conversations.vue";
import Knowledge from "./views/Knowledge.vue";
import Services from "./views/Services.vue";
import Account from "./views/Account.vue";
import Settings from "./views/Settings.vue";
import NotFound from "./views/NotFound.vue";

const VIEWS = {
	dashboard: Dashboard, tickets: Tickets, ticket: TicketDetail, "ticket-new": NewTicket,
	conversations: Conversations, conversation: Conversations, knowledge: Knowledge, article: Knowledge,
	services: Services, account: Account, settings: Settings,
};
const MODULE_OF = {
	tickets: "tickets", ticket: "tickets", "ticket-new": "tickets", conversations: "conversations",
	conversation: "conversations", knowledge: "knowledge", article: "knowledge", services: "services", account: "account",
};

const bootError = ref("");
const navOpen = ref(false);
const bellOpen = ref(false);
const menuOpen = ref(false);
const notifications = ref([]);
let poll;

const view = computed(() => {
	const mod = MODULE_OF[route.name];
	if (mod && !state.modules[mod]) return NotFound;
	return VIEWS[route.name] || NotFound;
});
const viewKey = computed(() => `${state.org}:${route.name}:${route.params.id || ""}`);

const navItems = computed(() => {
	const items = [
		{ name: "dashboard", path: "", icon: "home", label: "nav.dashboard" },
		{ name: "tickets", path: "tickets", icon: "ticket", label: "nav.tickets", module: "tickets" },
		{ name: "conversations", path: "conversations", icon: "chat", label: "nav.conversations", module: "conversations" },
		{ name: "knowledge", path: "knowledge", icon: "book", label: "nav.knowledge", module: "knowledge" },
		{ name: "services", path: "services", icon: "grid", label: "nav.services", module: "services" },
		{ name: "account", path: "account", icon: "receipt", label: "nav.account", module: "account",
			show: () => can("orders.read") || can("invoices.read") || can("documents.read") },
		{ name: "settings", path: "settings", icon: "settings", label: "nav.settings" },
	];
	return items.filter((i) => (!i.module || state.modules[i.module]) && (!i.show || i.show()));
});

const initials = computed(() =>
	(state.user?.full_name || "?").split(" ").map((p) => p[0]).slice(0, 2).join("").toUpperCase()
);

function isActive(item) {
	if (item.name === "dashboard") return route.name === "dashboard";
	return route.name.startsWith(item.name.replace(/s$/, ""));
}

async function load() {
	bootError.value = "";
	try {
		applyBoot(await call("portal.boot", {}, { org: false }));
		refreshCounters();
	} catch (e) {
		bootError.value = e.message;
	}
}

async function refreshCounters() {
	if (!state.linked || document.hidden) return;
	try {
		const n = await call("notifications.list_notifications", { limit: 20 }, { org: false });
		notifications.value = n.items;
		state.unreadNotifications = n.unread;
		if (state.modules.conversations && state.org) {
			state.unreadMessages = (await call("conversations.unread")).unread;
		}
	} catch (e) {
		/* counters are best-effort */
	}
}

function switchOrg(customer) {
	setOrg(customer);
	refreshCounters();
}

function toggleBell() {
	bellOpen.value = !bellOpen.value;
	menuOpen.value = false;
}

function closePops() {
	bellOpen.value = false;
	menuOpen.value = false;
}

function notifLink(n) {
	const map = {
		"HD Ticket": `tickets/${n.document_name}`, "Support Conversation Link": `conversations/${n.document_name}`,
		"Support Request": "services", "Sales Invoice": "account",
	};
	return link(map[n.document_type] || "");
}

async function openNotif(n) {
	bellOpen.value = false;
	if (n.read) return;
	n.read = 1;
	state.unreadNotifications = Math.max(0, state.unreadNotifications - 1);
	call("notifications.mark_read", { names: [n.name] }, { post: true, org: false }).catch(() => {});
}

async function markAll() {
	await call("notifications.mark_read", { all: 1 }, { post: true, org: false });
	notifications.value.forEach((n) => (n.read = 1));
	state.unreadNotifications = 0;
}

watch(() => route.name, () => (navOpen.value = false));

onMounted(() => {
	load();
	poll = setInterval(refreshCounters, 30000);
	document.addEventListener("visibilitychange", refreshCounters);
	window.__txNavigate = navigate;
});
onBeforeUnmount(() => {
	clearInterval(poll);
	document.removeEventListener("visibilitychange", refreshCounters);
});
</script>
