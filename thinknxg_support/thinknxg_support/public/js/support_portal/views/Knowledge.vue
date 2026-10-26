<template>
	<section>
		<template v-if="route.name === 'article'">
			<a :href="link('knowledge')" data-nav class="tx-backlink"><Icon name="back" size="16" />{{ state.t("kb.title") }}</a>
			<Loader :loading="loading" :error="error" @retry="loadArticle">
				<article v-if="article" class="tx-card tx-article">
					<p v-if="article.category" class="tx-eyebrow">{{ categoryLabel(article.category) }}</p>
					<h1>{{ article.title }}</h1>
					<small class="tx-muted">{{ fmtDate(article.modified) }}</small>
					<div class="tx-prose" v-html="article.content"></div>
				</article>
				<div v-if="state.modules.tickets" class="tx-card tx-cta">
					<span>{{ state.t("kb.not_helpful") }}</span>
					<a :href="link('tickets/new')" data-nav class="tx-btn tx-btn--primary">{{ state.t("kb.raise") }}</a>
				</div>
			</Loader>
		</template>

		<template v-else>
			<div class="tx-pagehead"><h1>{{ state.t("kb.title") }}</h1></div>
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
	</section>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { call } from "../api";
import { link, route } from "../router";
import { state, fmtDate } from "../store";
import Icon from "../components/Icon.vue";
import { Empty, Loader } from "../components/ui";

const q = ref(route.query.q || "");
const category = ref("");
const categories = ref([]);
const results = ref([]);
const article = ref(null);
const loading = ref(true);
const error = ref("");

const categoryLabel = (name) => categories.value.find((c) => c.name === name)?.label || name;

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
	} catch (e) {
		error.value = e.message;
	} finally {
		loading.value = false;
	}
}

onMounted(async () => {
	call("knowledge.categories", {}, { org: false }).then((c) => (categories.value = c)).catch(() => {});
	if (route.name === "article") loadArticle();
	else search();
});
</script>
