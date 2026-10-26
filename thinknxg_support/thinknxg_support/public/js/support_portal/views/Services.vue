<template>
	<section>
		<div class="tx-pagehead"><h1>{{ state.t("services.title") }}</h1></div>
		<div class="tx-seg tx-mb" role="tablist">
			<button v-for="tb in tabs" :key="tb.id" role="tab" :aria-selected="tab === tb.id" :class="{ on: tab === tb.id }"
				@click="tab = tb.id">{{ state.t(tb.label) }}</button>
		</div>

		<Loader :loading="loading" :error="error" @retry="load">
			<div v-if="tab === 'catalogue'" class="tx-cards">
				<Empty v-if="!catalogue.length" icon="grid" />
				<div v-for="s in catalogue" :key="s.name" class="tx-card tx-svc">
					<small v-if="s.category" class="tx-eyebrow">{{ s.category }}</small>
					<strong>{{ s.name }}</strong>
					<p>{{ s.description }}</p>
					<small v-if="s.response_target" class="tx-muted">{{ s.response_target }}</small>
					<button class="tx-btn tx-btn--primary tx-btn--sm" @click="openForm(s)">{{ state.t("services.request") }}</button>
				</div>
			</div>

			<div v-else-if="tab === 'requests'" class="tx-card tx-card--flush">
				<Empty v-if="!requests.length" icon="grid" />
				<button v-for="r in requests" :key="r.name" class="tx-row tx-row--btn" @click="openRequest(r)">
					<span class="tx-row__main">
						<strong>{{ r.subject }}</strong>
						<small>{{ r.name }} · {{ r.service || "" }} · {{ fmtDate(r.modified, true) }}
							<template v-if="r.helpdesk_ticket"> · #{{ r.helpdesk_ticket }}</template></small>
					</span>
					<Badge :status="r.status" />
				</button>
			</div>

			<div v-else class="tx-card tx-card--flush">
				<Empty v-if="!subs.length" icon="file" />
				<table v-else class="tx-table">
					<thead><tr><th>#</th><th>{{ state.t("services.plans") }}</th><th>{{ state.t("services.ends") }}</th><th>{{ state.t("common.status") }}</th></tr></thead>
					<tbody>
						<tr v-for="s in subs" :key="s.name">
							<td class="tx-mono">{{ s.name }}</td>
							<td>{{ s.plans.map((p) => `${p.plan} × ${p.qty}`).join(", ") }}</td>
							<td>{{ fmtDate(s.end_date || s.current_invoice_end) }}</td>
							<td><Badge :status="s.status" /></td>
						</tr>
					</tbody>
				</table>
			</div>
		</Loader>

		<div v-if="form" class="tx-modal" role="dialog" aria-modal="true" @click.self="form = null">
			<form class="tx-card tx-form tx-modal__body" @submit.prevent="submit">
				<h2>{{ form.service.name }}</h2>
				<p v-if="form.service.instructions" class="tx-muted">{{ form.service.instructions }}</p>
				<label class="tx-field"><span>{{ state.t("tickets.subject") }}</span>
					<input v-model="form.subject" required minlength="3" maxlength="140" /></label>
				<label class="tx-field"><span>{{ state.t("services.details") }}</span>
					<textarea v-model="form.details" rows="5" required maxlength="20000"></textarea></label>
				<div class="tx-formrow">
					<label class="tx-field"><span>{{ state.t("services.priority") }}</span>
						<select v-model="form.priority"><option v-for="p in ['Low', 'Medium', 'High', 'Urgent']" :key="p">{{ p }}</option></select>
					</label>
					<label v-if="refOptions.length" class="tx-field"><span>{{ state.t("services.related") }} ({{ state.t("common.optional") }})</span>
						<select v-model="form.ref">
							<option value="">—</option>
							<option v-for="o in refOptions" :key="o.value" :value="o.value">{{ o.label }}</option>
						</select>
					</label>
				</div>
				<div class="tx-formactions">
					<button type="button" class="tx-btn tx-btn--ghost" @click="form = null">{{ state.t("common.cancel") }}</button>
					<button class="tx-btn tx-btn--primary" :disabled="busy">{{ state.t("common.submit") }}</button>
				</div>
			</form>
		</div>

		<div v-if="viewing" class="tx-modal" role="dialog" aria-modal="true" @click.self="viewing = null">
			<div class="tx-card tx-modal__body">
				<div class="tx-card__head"><h2>{{ viewing.subject }}</h2><Badge :status="viewing.status" /></div>
				<small class="tx-muted">{{ viewing.name }} · {{ fmtDate(viewing.creation, true) }}</small>
				<div class="tx-prose" v-html="viewing.details"></div>
				<template v-if="viewing.customer_response">
					<h3>{{ state.t("services.response") }}</h3>
					<div class="tx-prose tx-quote" v-html="viewing.customer_response"></div>
				</template>
				<a v-if="viewing.helpdesk_ticket" :href="link('tickets/' + viewing.helpdesk_ticket)" data-nav class="tx-link">#{{ viewing.helpdesk_ticket }}</a>
				<div class="tx-formactions"><button class="tx-btn tx-btn--ghost" @click="viewing = null">{{ state.t("common.close") }}</button></div>
			</div>
		</div>
	</section>
</template>

<script setup>
import { computed, onMounted, ref } from "vue";
import { call } from "../api";
import { link, route } from "../router";
import { state, can, fmtDate, toast } from "../store";
import { textToHtml } from "../text";
import { Badge, Empty, Loader } from "../components/ui";

const tab = ref(route.query.tab || "catalogue");
const catalogue = ref([]);
const requests = ref([]);
const subs = ref([]);
const loading = ref(true);
const error = ref("");
const form = ref(null);
const viewing = ref(null);
const busy = ref(false);
const refOptions = ref([]);

const tabs = computed(() => [
	{ id: "catalogue", label: "services.catalogue" },
	{ id: "requests", label: "services.my_requests" },
	{ id: "subscriptions", label: "services.subscriptions" },
]);

async function load() {
	loading.value = true;
	error.value = "";
	try {
		const [c, r, s] = await Promise.all([
			call("services.catalogue"),
			call("services.my_requests", { scope: can("services.organization") ? "organization" : "own" }),
			call("services.subscriptions").catch(() => []),
		]);
		catalogue.value = c;
		requests.value = r;
		subs.value = s;
	} catch (e) {
		error.value = e.message;
	} finally {
		loading.value = false;
	}
}

async function loadRefs() {
	const opts = [];
	try {
		if (can("orders.read") && state.modules.account) {
			(await call("account.orders", { page_length: 20 })).forEach((o) =>
				opts.push({ value: `Sales Order::${o.name}`, label: `${o.name} · ${fmtDate(o.transaction_date)}` }));
		}
		if (can("invoices.read") && state.modules.account) {
			(await call("account.invoices", { page_length: 20 })).forEach((o) =>
				opts.push({ value: `Sales Invoice::${o.name}`, label: `${o.name} · ${fmtDate(o.posting_date)}` }));
		}
	} catch (e) {
		/* related documents are optional */
	}
	if (route.query.ref_doctype && route.query.ref_name) {
		const v = `${route.query.ref_doctype}::${route.query.ref_name}`;
		if (!opts.some((o) => o.value === v)) opts.unshift({ value: v, label: route.query.ref_name });
	}
	refOptions.value = opts;
}

function openForm(service) {
	const pre = route.query.ref_doctype && route.query.ref_name ? `${route.query.ref_doctype}::${route.query.ref_name}` : "";
	form.value = { service, subject: route.query.ref_name ? `${service.name}: ${route.query.ref_name}` : "",
		details: "", priority: "Medium", ref: pre };
	loadRefs();
}

async function openRequest(r) {
	try {
		viewing.value = await call("services.get_request", { name: r.name });
	} catch (e) {
		toast(e.message, "error");
	}
}

async function submit() {
	busy.value = true;
	const [refDt, refName] = form.value.ref ? form.value.ref.split("::") : [null, null];
	try {
		await call("services.create_request", {
			service: form.value.service.name, subject: form.value.subject, details: textToHtml(form.value.details),
			priority: form.value.priority, reference_doctype: refDt, reference_name: refName,
		}, { post: true });
		toast(state.t("services.submitted"));
		form.value = null;
		tab.value = "requests";
		await load();
	} catch (e) {
		toast(e.message, "error");
	} finally {
		busy.value = false;
	}
}

onMounted(load);
</script>
