<template>
	<section>
		<div class="tx-pagehead">
			<h1>{{ state.t("tickets.title") }}</h1>
			<a :href="link('tickets/new')" data-nav class="tx-btn tx-btn--primary">
				<Icon name="plus" size="16" />{{ state.t("tickets.new") }}
			</a>
		</div>

		<div class="tx-toolbar">
			<div v-if="can('tickets.organization')" class="tx-seg" role="tablist">
				<button role="tab" :aria-selected="scope === 'own'" :class="{ on: scope === 'own' }" @click="setScope('own')">
					{{ state.t("tickets.mine") }}</button>
				<button role="tab" :aria-selected="scope === 'organization'" :class="{ on: scope === 'organization' }"
					@click="setScope('organization')">{{ state.t("tickets.org") }}</button>
			</div>
			<div class="tx-chips">
				<button v-for="s in STATUSES" :key="s.value" class="tx-filter" :class="{ on: status === s.value }"
					@click="setStatus(s.value)">{{ state.t(s.label) }}</button>
			</div>
			<form class="tx-search" role="search" @submit.prevent="reload">
				<Icon name="search" size="16" />
				<input v-model.trim="search" type="search" :placeholder="state.t('tickets.search_ph')"
					:aria-label="state.t('common.search')" />
			</form>
		</div>

		<Loader :loading="loading && !rows.length" :error="error" @retry="reload">
			<div class="tx-card tx-card--flush">
				<Empty v-if="!rows.length" icon="ticket" />
				<table v-else class="tx-table">
					<thead>
						<tr>
							<th>#</th><th>{{ state.t("tickets.subject") }}</th><th class="tx-hide-sm">{{ state.t("tickets.priority") }}</th>
							<th class="tx-hide-sm">{{ state.t("tickets.sla_resolution") }}</th><th>{{ state.t("common.status") }}</th>
						</tr>
					</thead>
					<tbody>
						<tr v-for="t in rows" :key="t.name" class="tx-clickable" @click="open(t)">
							<td class="tx-mono">{{ t.name }}</td>
							<td>
								<a :href="link('tickets/' + t.name)" data-nav class="tx-strong">{{ t.subject }}</a>
								<small class="tx-muted tx-block">{{ fmtDate(t.modified, true) }}
									<template v-if="scope === 'organization' && !t.is_mine"> · {{ state.t("tickets.org") }}</template></small>
							</td>
							<td class="tx-hide-sm">{{ t.priority || "—" }}</td>
							<td class="tx-hide-sm" :class="{ 'tx-danger': t.overdue }">
								{{ t.resolution_by ? fmtDate(t.resolution_by, true) : "—" }}
							</td>
							<td><Badge :status="t.overdue ? 'Overdue' : t.status_category" :label="t.status" /></td>
						</tr>
					</tbody>
				</table>
			</div>
			<div v-if="rows.length < total" class="tx-center">
				<button class="tx-btn tx-btn--ghost" :disabled="loading" @click="more">
					{{ state.t("common.view_all") }} ({{ rows.length }} {{ state.t("common.of") }} {{ total }})
				</button>
			</div>
		</Loader>
	</section>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { call } from "../api";
import { link, navigate, route } from "../router";
import { state, can, fmtDate } from "../store";
import Icon from "../components/Icon.vue";
import { Badge, Empty, Loader } from "../components/ui";

const STATUSES = [
	{ value: "", label: "tickets.all" }, { value: "Open", label: "tickets.open" },
	{ value: "Paused", label: "tickets.waiting" }, { value: "Resolved", label: "tickets.resolved" },
];
const rows = ref([]);
const total = ref(0);
const loading = ref(false);
const error = ref("");
const scope = ref(route.query.scope === "organization" ? "organization" : "own");
const status = ref(route.query.status || "");
const search = ref("");

async function fetchPage(start) {
	loading.value = true;
	error.value = "";
	try {
		const r = await call("tickets.list_tickets", {
			scope: scope.value, status: status.value, search: search.value, start, page_length: 20,
		});
		rows.value = start ? rows.value.concat(r.tickets) : r.tickets;
		total.value = r.total;
	} catch (e) {
		error.value = e.message;
	} finally {
		loading.value = false;
	}
}
const reload = () => fetchPage(0);
const more = () => fetchPage(rows.value.length);
const setScope = (s) => { scope.value = s; reload(); };
const setStatus = (s) => { status.value = s; reload(); };
const open = (t) => navigate("tickets/" + t.name);

onMounted(reload);
</script>
