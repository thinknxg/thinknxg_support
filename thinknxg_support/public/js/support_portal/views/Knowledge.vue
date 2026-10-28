<template>
	<section class="tx-kb">
		<!-- Category-wise navigation (like a wiki sidebar). On phones it folds into a "Browse articles" button. -->
		<aside class="tx-kb__side" :class="{ open: navOpen }" :aria-label="state.t('kb.browse')">
			<button type="button" class="tx-kb__toggle" :aria-expanded="navOpen" @click="navOpen = !navOpen">
				<Icon name="menu" size="16" /><span>{{ state.t("kb.browse") }}</span>
			</button>
			<div class="tx-kb__nav">
				<input v-model.trim="navFilter" type="search" class="tx-kb__filter" :placeholder="state.t('kb.filter')"
					:aria-label="state.t('kb.filter')" />
				<a :href="link('knowledge')" data-nav class="tx-kb__all" :class="{ on: route.name === 'knowledge' && !category }">
					<Icon name="book" size="16" />{{ state.t("kb.all") }}
				</a>
				<p v-if="!navGroups.length && navFilter" class="tx-muted tx-kb__none">{{ state.t("kb.no_match") }}</p>
				<details v-for="g in navGroups" :key="g.name || '_general'" class="tx-kb__group" :open="isOpen(g)">
					<summary>
						<span>{{ g.label }}</span><small>{{ g.articles.length }}</small>
					</summary>
					<ul>
						<li v-for="a in g.articles" :key="a.name">
							<a :href="link('knowledge/' + a.name)" data-nav :class="{ on: a.name === route.params.id }"
								:aria-current="a.name === route.params.id ? 'page' : null">{{ a.title }}</a>
						</li>
					</ul>
				</details>
			</div>
		</aside>

		<div class="tx-kb__main">
			<template v-if="route.name === 'article'">
				<a :href="link('knowledge')" data-nav class="tx-backlink"><Icon name="back" size="16" />{{ state.t("kb.title") }}</a>
				<Loader :loading="loading" :error="error" @retry="loadArticle">
					<article v-if="article" class="tx-card tx-article">
						<div class="tx-article__head">
							<div>
								<p v-if="article.category" class="tx-eyebrow">{{ categoryLabel(article.category) }}</p>
								<h1>{{ article.title }}</h1>
								<small class="tx-muted">{{ state.t("kb.updated") }} {{ fmtDate(article.modified) }}</small>
							</div>
							<button type="button" class="tx-btn tx-btn--ghost tx-btn--sm tx-copy" @click="copyLink">
								<Icon :name="copied ? 'check' : 'link'" size="16" />
								<span>{{ copied ? state.t("kb.copied") : state.t("kb.copy_link") }}</span>
							</button>
						</div>
						<div class="tx-prose" v-html="article.content"></div>
					</article>

					<!-- Was this article helpful? -->
					<div v-if="article" class="tx-card tx-feedback" aria-live="polite">
						<div class="tx-feedback__row">
							<strong>{{ state.t("kb.helpful_q") }}</strong>
							<div class="tx-feedback__votes" role="group" :aria-label="state.t('kb.helpful_q')">
								<button type="button" class="tx-vote" :class="{ on: vote === 'Helpful' }" :aria-pressed="vote === 'Helpful'"
									:disabled="voting" :title="state.t('kb.yes')" @click="sendVote('Helpful')">
									<Icon name="thumbs_up" size="18" /><span>{{ state.t("kb.yes") }}</span>
								</button>
								<button type="button" class="tx-vote" :class="{ on: vote === 'Not Helpful' }" :aria-pressed="vote === 'Not Helpful'"
									:disabled="voting" :title="state.t('kb.no')" @click="sendVote('Not Helpful')">
									<Icon name="thumbs_down" size="18" /><span>{{ state.t("kb.no") }}</span>
								</button>
							</div>
						</div>
						<p v-if="vote === 'Helpful'" class="tx-feedback__thanks">{{ state.t("kb.thanks") }}</p>
						<form v-if="vote === 'Not Helpful' && !commentSent" class="tx-feedback__more" @submit.prevent="sendComment">
							<label>
								<span>{{ state.t("kb.what_missing") }}</span>
								<textarea v-model.trim="comment" rows="2" maxlength="1000"></textarea>
							</label>
							<button class="tx-btn tx-btn--sm" :disabled="!comment || voting">{{ state.t("kb.send") }}</button>
						</form>
						<p v-if="commentSent" class="tx-feedback__thanks">{{ state.t("kb.thanks_comment") }}</p>

						<!-- If your issue isn't resolved, raise a support ticket -->
						<div class="tx-feedback__next">
							<span>{{ state.t("kb.not_resolved") }}</span>
							<a v-if="ticketHref" :href="ticketHref" :data-nav="state.isGuest || !state.linked ? null : ''"
								class="tx-btn tx-btn--primary tx-btn--sm">
								<Icon name="ticket" size="16" />{{ state.isGuest ? state.t("kb.login_raise") : state.t("kb.raise_here") }}
							</a>
							<button v-if="state.modules.chat" type="button" class="tx-btn tx-btn--sm" @click="openChat()">
								<Icon name="chat" size="16" />{{ state.t("kb.chat") }}
							</button>
						</div>
					</div>

					<!-- Related articles -->
					<section v-if="relatedArticles.length" class="tx-related" :aria-label="state.t('kb.related')">
						<h2>{{ state.t("kb.related") }}</h2>
						<div class="tx-related__list">
							<a v-for="r in relatedArticles" :key="r.name" :href="link('knowledge/' + r.name)" data-nav class="tx-card tx-kbcard">
								<small v-if="r.category" class="tx-eyebrow">{{ categoryLabel(r.category) }}</small>
								<strong>{{ r.title }}</strong>
							</a>
						</div>
					</section>
				</Loader>
			</template>

			<template v-else>
				<div class="tx-pagehead"><h1>{{ category ? categoryLabel(category) : state.t("kb.title") }}</h1></div>
				<form class="tx-search tx-search--hero" role="search" @submit.prevent="search">
					<Icon name="search" />
					<input v-model.trim="q" type="search" :placeholder="state.t('kb.search')" :aria-label="state.t('kb.search')" />
					<button class="tx-btn tx-btn--primary">{{ state.t("common.search") }}</button>
				</form>
				<div v-if="categories.length" class="tx-chips tx-mb">
					<button class="tx-filter" :class="{ on: !category }" @click="pick('')">{{ state.t("kb.all") }}</button>
					<button v-for="c in categories" :key="c.name" class="tx-filter" :class="{ on: category === c.name }"
						@click="pick(c.name)">{{ c.label }}</button>
				</div>
				<Loader :loading="loading" :error="error" @retry="search">
					<Empty v-if="!results.length" icon="book" />
					<div class="tx-cards">
						<a v-for="a in results" :key="a.name" :href="link('knowledge/' + a.name)" data-nav class="tx-card tx-kbcard">
							<small v-if="a.category" class="tx-eyebrow">{{ categoryLabel(a.category) }}</small>
							<strong>{{ a.title }}</strong>
							<p>{{ a.excerpt }}</p>
						</a>
					</div>
				</Loader>
			</template>
		</div>
	</section>
</template>

<script setup>
import { computed, onMounted, ref } from "vue";
import { call } from "../api";
import { link, route } from "../router";
import { state, fmtDate, loginUrl, openChat, toast } from "../store";
import Icon from "../components/Icon.vue";
import { Empty, Loader } from "../components/ui";

const q = ref(route.query.q || "");
const category = ref(route.query.category || "");
const categories = ref([]);
const groups = ref([]);
const results = ref([]);
const article = ref(null);
const relatedArticles = ref([]);
const loading = ref(true);
const error = ref("");
const navOpen = ref(false);
const navFilter = ref("");
const copied = ref(false);
const vote = ref(null);
const voting = ref(false);
const comment = ref("");
const commentSent = ref(false);

const categoryLabel = (name) =>
	categories.value.find((c) => c.name === name)?.label || groups.value.find((g) => g.name === name)?.label || name;

const navGroups = computed(() => {
	const f = navFilter.value.toLowerCase();
	if (!f) return groups.value;
	return groups.value
		.map((g) => ({ ...g, articles: g.articles.filter((a) => a.title.toLowerCase().includes(f)) }))
		.filter((g) => g.articles.length || g.label.toLowerCase().includes(f));
});

// The group holding the open article (or the chosen category) starts expanded; with a filter, all do.
function isOpen(g) {
	if (navFilter.value) return true;
	if (route.name === "article") return g.articles.some((a) => a.name === route.params.id);
	return category.value ? g.name === category.value : groups.value.length <= 3;
}

const shareUrl = computed(() => window.location.origin + link("knowledge/" + (route.params.id || "")));

const ticketHref = computed(() => {
	if (!state.modules.tickets || !article.value) return null;
	const qs = new URLSearchParams({ subject: article.value.title, article: shareUrl.value }).toString();
	const path = link("tickets/new") + "?" + qs;
	return state.isGuest || !state.linked ? loginUrl(path) : path;
});

async function copyLink() {
	const url = shareUrl.value;
	try {
		await navigator.clipboard.writeText(url);
	} catch {
		// Older browsers or a page without clipboard permission: copy through a hidden field.
		const el = document.createElement("textarea");
		el.value = url;
		el.setAttribute("readonly", "");
		el.style.position = "fixed";
		el.style.opacity = "0";
		document.body.appendChild(el);
		el.select();
		try {
			document.execCommand("copy");
		} catch {
			window.prompt(state.t("kb.copy_link"), url);
		}
		el.remove();
	}
	copied.value = true;
	toast(state.t("kb.copied"));
	setTimeout(() => (copied.value = false), 2500);
}

async function sendVote(v) {
	if (voting.value) return;
	voting.value = true;
	const before = vote.value;
	vote.value = v;
	commentSent.value = false;
	try {
		await call("knowledge.feedback", { name: route.params.id, vote: v }, { post: true, org: false });
	} catch (e) {
		vote.value = before;
		toast(e.message, "error");
	} finally {
		voting.value = false;
	}
}

async function sendComment() {
	voting.value = true;
	try {
		await call("knowledge.feedback", { name: route.params.id, vote: "Not Helpful", comment: comment.value },
			{ post: true, org: false });
		commentSent.value = true;
	} catch (e) {
		toast(e.message, "error");
	} finally {
		voting.value = false;
	}
}

async function search() {
	loading.value = true;
	error.value = "";
	try {
		results.value = await call("knowledge.search", { q: q.value, category: category.value, limit: 30 }, { org: false });
	} catch (e) {
		error.value = e.message;
	} finally {
		loading.value = false;
	}
}

function pick(c) {
	category.value = c;
	search();
}

async function loadArticle() {
	loading.value = true;
	error.value = "";
	try {
		article.value = await call("knowledge.article", { name: route.params.id }, { org: false });
		vote.value = article.value.my_vote || null;
		document.title = article.value.title + " · " + (state.branding?.portal_title || "");
		call("knowledge.related", { name: route.params.id, limit: 5 }, { org: false })
			.then((r) => (relatedArticles.value = r || []))
			.catch(() => {});
	} catch (e) {
		error.value = e.message;
	} finally {
		loading.value = false;
	}
}

onMounted(async () => {
	call("knowledge.categories", {}, { org: false }).then((c) => (categories.value = c)).catch(() => {});
	call("knowledge.sidebar", {}, { org: false }).then((g) => (groups.value = g || [])).catch(() => {});
	if (route.name === "article") loadArticle();
	else search();
});
</script>
