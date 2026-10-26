<template>
	<section>
		<div class="tx-pagehead">
			<div>
				<p class="tx-eyebrow">{{ orgName }}</p>
				<h1>{{ state.t("dash.welcome") }}, {{ firstName }}</h1>
			</div>
			<div class="tx-actions">
				<a v-if="state.modules.tickets" :href="link('tickets/new')" data-nav class="tx-btn tx-btn--primary">
					<Icon name="plus" size="16" />{{ state.t("dash.new_ticket") }}
				</a>
				<a v-if="state.modules.conversations" :href="link('conversations?new=1')" data-nav class="tx-btn tx-btn--ghost">
					<Icon name="chat" size="16" />{{ state.t("dash.new_message") }}
				</a>
			</div>
		</div>

		<Loader :loading="loading" :error="error" @retry="load">
			<div v-if="data.announcement" class="tx-announce">{{ data.announcement }}</div>

			<div class="tx-stats">
				<template v-if="data.tickets">
					<a :href="link('tickets?status=Open')" data-nav class="tx-stat">
						<span class="tx-stat__n">{{ data.tickets.open }}</span><span>{{ state.t("dash.open") }}</span>
					</a>
					<a :href="link('tickets?status=Paused')" data-nav class="tx-stat tx-stat--warn">
						<span class="tx-stat__n">{{ data.tickets.waiting }}</span><span>{{ state.t("dash.waiting") }}</span>
					</a>
					<a :href="link('tickets?status=Resolved')" data-nav class="tx-stat tx-stat--ok">
						<span class="tx-stat__n">{{ data.tickets.resolved }}</span><span>{{ state.t("dash.resolved") }}</span>
					</a>
					<div v-if="data.tickets.overdue" class="tx-stat tx-stat--danger">
						<span class="tx-stat__n">{{ data.tickets.overdue }}</span><span>{{ state.t("dash.overdue") }}</span>
					</div>
				</template>
				<a v-if="data.unread_messages !== undefined" :href="link('conversations')" data-nav class="tx-stat">
					<span class="tx-stat__n">{{ data.unread_messages }}</span><span>{{ state.t("dash.unread") }}</span>
				</a>
				<a v-for="s in data.statement || []" :key="s.currency" :href="link('account?tab=statement')" data-nav
					class="tx-stat" :class="{ 'tx-stat--danger': s.overdue > 0 }">
					<span class="tx-stat__n tx-stat__n--money">{{ fmtMoney(s.outstanding, s.currency) }}</span>
					<span>{{ state.t("dash.outstanding") }}</span>
				</a>
			</div>

			<div class="tx-grid2">
				<div v-if="data.tickets" class="tx-card">
					<div class="tx-card__head">
						<h2>{{ state.t("dash.recent_tickets") }}</h2>
						<a :href="link('tickets')" data-nav class="tx-link">{{ state.t("common.view_all") }}</a>
					</div>
					<Empty v-if="!data.tickets.recent.length" icon="ticket" />
					<a v-for="t in data.tickets.recent" :key="t.name" :href="link('tickets/' + t.name)" data-nav class="tx-row">
						<span class="tx-row__main">
							<strong>#{{ t.name }} · {{ t.subject }}</strong>
							<small>{{ fmtDate(t.modified, true) }}</small>
						</span>
						<Badge :status="t.status_category" :label="t.status" />
					</a>
				</div>

				<div v-if="data.recent_conversations" class="tx-card">
					<div class="tx-card__head">
						<h2>{{ state.t("dash.recent_messages") }}</h2>
						<a :href="link('conversations')" data-nav class="tx-link">{{ state.t("common.view_all") }}</a>
					</div>
					<Empty v-if="!data.recent_conversations.length" icon="chat" />
					<a v-for="c in data.recent_conversations" :key="c.name" :href="link('conversations/' + c.name)" data-nav class="tx-row">
						<span class="tx-row__main">
							<strong>{{ c.subject }}</strong>
							<small>{{ fmtDate(c.last_activity_at, true) }}</small>
						</span>
						<span v-if="c.unread" class="tx-count">{{ c.unread }}</span>
						<Badge v-else :status="c.status" />
					</a>
				</div>

				<div v-if="data.recent_requests" class="tx-card">
					<div class="tx-card__head">
						<h2>{{ state.t("dash.requests") }}</h2>
						<a :href="link('services')" data-nav class="tx-link">{{ state.t("dash.browse_services") }}</a>
					</div>
					<Empty v-if="!data.recent_requests.length" icon="grid" />
					<div v-for="r in data.recent_requests" :key="r.name" class="tx-row">
						<span class="tx-row__main"><strong>{{ r.subject }}</strong><small>{{ r.name }}</small></span>
						<Badge :status="r.status" />
					</div>
				</div>

				<div v-if="data.articles && data.articles.length" class="tx-card">
					<div class="tx-card__head">
						<h2>{{ state.t("dash.articles") }}</h2>
						<a :href="link('knowledge')" data-nav class="tx-link">{{ state.t("common.view_all") }}</a>
					</div>
					<a v-for="a in data.articles" :key="a.name" :href="link('knowledge/' + a.name)" data-nav class="tx-row">
						<span class="tx-row__main"><strong>{{ a.title }}</strong><small>{{ a.excerpt }}</small></span>
					</a>
				</div>
			</div>
		</Loader>
	</section>
</template>

<script setup>
import { computed, onMounted, ref } from "vue";
import { call } from "../api";
import { link } from "../router";
import { state, currentOrg, fmtDate, fmtMoney } from "../store";
import Icon from "../components/Icon.vue";
import { Badge, Empty, Loader } from "../components/ui";

const data = ref({});
const loading = ref(true);
const error = ref("");
const orgName = computed(() => currentOrg()?.customer_name || "");
const firstName = computed(() => (state.user?.full_name || "").split(" ")[0]);

async function load() {
	loading.value = true;
	error.value = "";
	try {
		data.value = await call("dashboard.get_dashboard");
	} catch (e) {
		error.value = e.message;
	} finally {
		loading.value = false;
	}
}
onMounted(load);
</script>
