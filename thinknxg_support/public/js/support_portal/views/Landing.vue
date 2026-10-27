<template>
	<div class="tx-land">
		<Loader :loading="loading" :error="error" @retry="load">
			<p v-if="!state.isGuest && !state.linked" class="tx-land-note" role="status">{{ state.t("land.unlinked") }}</p>

			<section v-for="(s, i) in sections" :key="i" class="tx-land-band" :class="['tx-land-band--' + (s.style || 'Plain').toLowerCase(), 'tx-land-' + slug(s.type)]">
				<div class="tx-land-inner">

					<!-- Hero -->
					<div v-if="s.type === 'Hero'" class="tx-hero" :class="{ 'tx-hero--image': s.image }">
						<div class="tx-hero__text">
							<h1>{{ s.title || state.t("land.hero") }}</h1>
							<p v-if="s.subtitle">{{ s.subtitle }}</p>
							<form v-if="s.search" class="tx-hero__search" role="search" @submit.prevent="search">
								<Icon name="search" />
								<input id="tx-land-q" v-model.trim="q" type="search" :placeholder="state.t('land.search_ph')"
									:aria-label="state.t('land.search')" />
								<button class="tx-btn tx-btn--primary">{{ state.t("land.search") }}</button>
							</form>
							<a v-if="s.button" :href="href(s.button.link)" class="tx-btn tx-hero__btn" v-bind="extAttrs(s.button.link)"
								:data-nav="isPortal(s.button.link) ? '' : null">{{ s.button.label }}</a>
						</div>
						<img v-if="s.image" :src="s.image" alt="" class="tx-hero__img" />
					</div>

					<!-- Quick actions -->
					<template v-else-if="s.type === 'Quick Actions'">
						<h2 class="tx-land-h">{{ s.title || state.t("land.actions") }}</h2>
						<p v-if="s.subtitle" class="tx-land-sub">{{ s.subtitle }}</p>
						<div class="tx-qa">
							<a v-for="a in s.actions" :key="a.key" :href="actionHref(a)" class="tx-qa__item"
								v-bind="a.key === 'whatsapp' ? { target: '_blank', rel: 'noopener' } : {}"
								:data-nav="actionNav(a) ? '' : null" @click="actionClick($event, a)">
								<span class="tx-qa__icon"><Icon :name="ACTION_ICON[a.key]" size="22" /></span>
								<span class="tx-qa__text">
									<strong>{{ qa(a.key)[0] }}</strong>
									<small>{{ qa(a.key)[1] }}</small>
								</span>
								<span v-if="a.login" class="tx-qa__lock" :title="state.t('land.login_hint')"><Icon name="login" size="14" /></span>
							</a>
						</div>
					</template>

					<!-- Account summary -->
					<template v-else-if="s.type === 'Account Summary'">
						<div class="tx-land-headrow">
							<h2 class="tx-land-h">{{ s.title || state.t("land.summary") }}</h2>
							<a :href="link('dashboard')" data-nav class="tx-link">{{ state.t("land.go_dashboard") }}</a>
						</div>
						<div class="tx-stats">
							<a v-if="summary.tickets" :href="link('tickets?status=Open')" data-nav class="tx-stat">
								<span class="tx-stat__n">{{ summary.tickets.open }}</span><span>{{ state.t("land.open_tickets") }}</span></a>
							<a v-if="summary.tickets" :href="link('tickets?status=Paused')" data-nav class="tx-stat tx-stat--warn">
								<span class="tx-stat__n">{{ summary.tickets.waiting }}</span><span>{{ state.t("land.waiting") }}</span></a>
							<a v-if="summary.unread_messages !== undefined" :href="link('conversations')" data-nav class="tx-stat">
								<span class="tx-stat__n">{{ summary.unread_messages }}</span><span>{{ state.t("land.unread") }}</span></a>
							<a v-for="b in summary.statement || []" :key="b.currency" :href="link('account?tab=statement')" data-nav
								class="tx-stat" :class="{ 'tx-stat--danger': b.overdue > 0 }">
								<span class="tx-stat__n tx-stat__n--money">{{ fmtMoney(b.outstanding, b.currency) }}</span>
								<span>{{ state.t("land.outstanding") }}</span></a>
						</div>
					</template>

					<!-- Popular articles -->
					<template v-else-if="s.type === 'Popular Articles'">
						<div class="tx-land-headrow">
							<h2 class="tx-land-h">{{ s.title || state.t("land.articles") }}</h2>
							<a :href="link('knowledge')" data-nav class="tx-link">{{ state.t("land.view_all") }}</a>
						</div>
						<p v-if="s.subtitle" class="tx-land-sub">{{ s.subtitle }}</p>
						<div class="tx-land-list">
							<a v-for="a in s.articles" :key="a.name" :href="link('knowledge/' + a.name)" data-nav class="tx-land-article">
								<Icon name="book" size="18" />
								<span><strong>{{ a.title }}</strong><small>{{ a.excerpt }}</small></span>
							</a>
						</div>
					</template>

					<!-- Categories -->
					<template v-else-if="s.type === 'Knowledge Categories'">
						<h2 class="tx-land-h">{{ s.title || state.t("land.categories") }}</h2>
						<p v-if="s.subtitle" class="tx-land-sub">{{ s.subtitle }}</p>
						<div class="tx-land-chips">
							<a v-for="c in s.categories" :key="c.name" :href="link('knowledge?category=' + encodeURIComponent(c.name))" data-nav
								class="tx-land-chip">{{ c.label }}</a>
						</div>
					</template>

					<!-- Services -->
					<template v-else-if="s.type === 'Services'">
						<div class="tx-land-headrow">
							<h2 class="tx-land-h">{{ s.title || state.t("land.services") }}</h2>
						</div>
						<p v-if="s.subtitle" class="tx-land-sub">{{ s.subtitle }}</p>
						<div class="tx-land-grid">
							<article v-for="x in s.services" :key="x.name" class="tx-land-card">
								<small v-if="x.category" class="tx-eyebrow">{{ x.category }}</small>
								<strong>{{ x.name }}</strong>
								<p>{{ x.description }}</p>
								<small v-if="x.response_target" class="tx-muted"><Icon name="clock" size="13" /> {{ x.response_target }}</small>
								<a :href="state.isGuest || !state.linked ? loginUrl(base + '/services') : link('services')"
									:data-nav="state.isGuest || !state.linked ? null : ''" class="tx-link">{{ state.t("land.request") }} →</a>
							</article>
						</div>
					</template>

					<!-- FAQ -->
					<template v-else-if="s.type === 'FAQ'">
						<h2 class="tx-land-h">{{ s.title || state.t("land.faq") }}</h2>
						<p v-if="s.subtitle" class="tx-land-sub">{{ s.subtitle }}</p>
						<div class="tx-faq">
							<details v-for="(f, j) in s.faq" :key="j" class="tx-faq__item">
								<summary>{{ f.q }}</summary>
								<div class="tx-prose" v-html="f.a"></div>
							</details>
						</div>
					</template>

					<!-- Contact and hours -->
					<template v-else-if="s.type === 'Contact and Hours'">
						<h2 class="tx-land-h">{{ s.title || state.t("land.contact") }}</h2>
						<p v-if="s.subtitle" class="tx-land-sub">{{ s.subtitle }}</p>
						<div class="tx-contact">
							<div class="tx-contact__status" :class="{ on: s.contact.online }">
								<span class="tx-contact__dot"></span>
								<strong>{{ s.contact.online ? state.t("land.online") : state.t("land.offline") }}</strong>
								<span v-if="s.contact.days.length">{{ hours(s.contact) }}</span>
								<button v-if="s.contact.chat" type="button" class="tx-btn tx-btn--primary tx-btn--sm" @click="openChat()">
									{{ state.t("land.chat_now") }}</button>
							</div>
							<div v-if="s.contact.email" class="tx-contact__item"><Icon name="mail" /><span><small>{{ state.t("land.email") }}</small>
								<span class="tx-select">{{ s.contact.email }}</span></span></div>
							<div v-if="s.contact.phone" class="tx-contact__item"><Icon name="phone" /><span><small>{{ state.t("land.phone") }}</small>
								<span class="tx-select" dir="ltr">{{ s.contact.phone }}</span></span></div>
							<a v-if="s.contact.whatsapp" :href="s.contact.whatsapp" target="_blank" rel="noopener" class="tx-contact__item tx-contact__item--link">
								<Icon name="whatsapp" /><span><small>{{ state.t("land.whatsapp") }}</small><span>{{ state.t("land.qa.whatsapp")[0] }}</span></span></a>
						</div>
					</template>

					<!-- Announcement -->
					<div v-else-if="s.type === 'Announcement'" class="tx-land-announce">
						<Icon name="bell" />
						<div>
							<strong v-if="s.title">{{ s.title }}</strong>
							<div class="tx-prose" v-html="s.html"></div>
							<a v-if="s.button" :href="href(s.button.link)" class="tx-link" v-bind="extAttrs(s.button.link)"
								:data-nav="isPortal(s.button.link) ? '' : null">{{ s.button.label }} →</a>
						</div>
					</div>

					<!-- Cards -->
					<template v-else-if="s.type === 'Cards'">
						<h2 v-if="s.title" class="tx-land-h">{{ s.title }}</h2>
						<p v-if="s.subtitle" class="tx-land-sub">{{ s.subtitle }}</p>
						<div class="tx-land-grid">
							<component :is="c.link ? 'a' : 'article'" v-for="(c, j) in s.cards" :key="j" class="tx-land-card"
								:class="{ 'tx-land-card--link': c.link }" :href="c.link ? href(c.link) : null"
								v-bind="c.link ? extAttrs(c.link) : {}" :data-nav="c.link && isPortal(c.link) ? '' : null">
								<strong>{{ c.title }} <Icon v-if="c.link && isExternal(c.link)" name="external" size="13" /></strong>
								<p v-if="c.text">{{ c.text }}</p>
							</component>
						</div>
					</template>

					<!-- Custom content -->
					<template v-else-if="s.type === 'Custom Content'">
						<h2 v-if="s.title" class="tx-land-h">{{ s.title }}</h2>
						<div class="tx-prose tx-land-custom" v-html="s.html"></div>
					</template>

					<!-- Call to action -->
					<div v-else-if="s.type === 'Call to Action'" class="tx-cta-band">
						<div>
							<h2>{{ s.title }}</h2>
							<p v-if="s.subtitle">{{ s.subtitle }}</p>
						</div>
						<a v-if="s.button" :href="href(s.button.link)" class="tx-btn tx-cta-band__btn" v-bind="extAttrs(s.button.link)"
							:data-nav="isPortal(s.button.link) ? '' : null">{{ s.button.label }}</a>
					</div>
				</div>
			</section>
		</Loader>
	</div>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { call } from "../api";
import { link, navigate } from "../router";
import { state, fmtMoney, loginUrl, openChat } from "../store";
import Icon from "../components/Icon.vue";
import { Loader } from "../components/ui";

const ACTION_ICON = {
	ticket: "plus", chat: "chat", knowledge: "book", my_tickets: "ticket", orders: "receipt", services: "grid",
	whatsapp: "whatsapp", contact: "mail",
};
const sections = ref([]);
const summary = ref({});
const loading = ref(true);
const error = ref("");
const q = ref("");
const base = state.base;

const slug = (t) => String(t).toLowerCase().replace(/[^a-z]+/g, "-");
const qa = (key) => {
	const v = state.t("land.qa." + key);
	return Array.isArray(v) ? v : [key, ""];
};
const isExternal = (url) => /^https?:\/\//i.test(url || "") && !String(url).startsWith(window.location.origin);
const isPortal = (url) => typeof url === "string" && (url === base || url.startsWith(base + "/"));
const href = (url) => (url === "/login" ? loginUrl(base) : url);
const extAttrs = (url) => (isExternal(url) ? { target: "_blank", rel: "noopener" } : {});

function hours(c) {
	const d = c.days.map((x) => (state.t("land.days")[x] || x));
	const days = d.length > 2 && isRun(c.days) ? `${d[0]} – ${d[d.length - 1]}` : d.join(", ");
	return c.start && c.end ? `${days} · ${c.start}–${c.end}` : days;
}

function isRun(days) {
	const order = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
	const idx = days.map((x) => order.indexOf(x));
	return idx.every((v, i) => i === 0 || v === idx[i - 1] + 1);
}

function actionHref(a) {
	if (a.key === "whatsapp") return a.href;
	const path = { ticket: "tickets/new", knowledge: "knowledge", my_tickets: "tickets", orders: "account", services: "services",
		chat: "", contact: "" }[a.key];
	if (a.login) return loginUrl(base + "/" + path);
	return link(path);
}

function actionNav(a) {
	return !a.login && !["whatsapp", "chat", "contact"].includes(a.key);
}

function actionClick(e, a) {
	if (a.key === "chat") {
		e.preventDefault();
		openChat();
	} else if (a.key === "contact") {
		e.preventDefault();
		const el = document.querySelector(".tx-land-contact-and-hours");
		if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
	}
}

function search() {
	if (q.value) navigate("knowledge?q=" + encodeURIComponent(q.value));
}

async function load() {
	loading.value = true;
	error.value = "";
	try {
		const r = await call("portal.landing", {}, { org: false });
		sections.value = r.sections || [];
		if (sections.value.some((s) => s.type === "Account Summary") && state.linked && !state.isGuest) {
			call("dashboard.get_dashboard").then((d) => (summary.value = d)).catch(() => {});
		}
	} catch (e) {
		error.value = e.message;
	} finally {
		loading.value = false;
	}
}

onMounted(load);
</script>
