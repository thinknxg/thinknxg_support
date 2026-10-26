<template>
	<section>
		<div class="tx-pagehead"><h1>{{ state.t("account.title") }}</h1></div>
		<div class="tx-seg tx-mb" role="tablist">
			<button v-for="tb in tabs" :key="tb.id" role="tab" :aria-selected="tab === tb.id" :class="{ on: tab === tb.id }"
				@click="switchTab(tb.id)">{{ state.t(tb.label) }}</button>
		</div>

		<Loader :loading="loading" :error="error" @retry="load">
			<!-- Orders -->
			<div v-if="tab === 'orders'" class="tx-card tx-card--flush">
				<Empty v-if="!orders.length" icon="receipt" />
				<table v-else class="tx-table">
					<thead><tr><th>#</th><th>{{ state.t("common.date") }}</th><th class="tx-hide-sm">{{ state.t("account.delivered") }}</th>
						<th class="tx-num">{{ state.t("common.total") }}</th><th>{{ state.t("common.status") }}</th></tr></thead>
					<tbody>
						<tr v-for="o in orders" :key="o.name" class="tx-clickable" @click="openDoc('order', o.name)">
							<td class="tx-mono">{{ o.name }}<small v-if="o.po_no" class="tx-muted tx-block">PO {{ o.po_no }}</small></td>
							<td>{{ fmtDate(o.transaction_date) }}</td>
							<td class="tx-hide-sm"><span class="tx-progress"><span :style="{ width: (o.per_delivered || 0) + '%' }"></span></span></td>
							<td class="tx-num">{{ fmtMoney(o.grand_total, o.currency) }}</td>
							<td><Badge :status="o.status" /></td>
						</tr>
					</tbody>
				</table>
			</div>

			<!-- Invoices -->
			<div v-else-if="tab === 'invoices'">
				<label class="tx-check tx-mb"><input v-model="onlyOutstanding" type="checkbox" @change="load" /> {{ state.t("account.only_outstanding") }}</label>
				<div class="tx-card tx-card--flush">
					<Empty v-if="!invoices.length" icon="receipt" />
					<table v-else class="tx-table">
						<thead><tr><th>#</th><th>{{ state.t("common.date") }}</th><th class="tx-hide-sm">{{ state.t("account.due") }}</th>
							<th class="tx-num">{{ state.t("common.total") }}</th><th class="tx-num">{{ state.t("account.outstanding") }}</th>
							<th>{{ state.t("common.status") }}</th><th></th></tr></thead>
						<tbody>
							<tr v-for="i in invoices" :key="i.name" class="tx-clickable" @click="openDoc('invoice', i.name)">
								<td class="tx-mono">{{ i.name }}</td>
								<td>{{ fmtDate(i.posting_date) }}</td>
								<td class="tx-hide-sm">{{ fmtDate(i.due_date) }}</td>
								<td class="tx-num">{{ fmtMoney(i.grand_total, i.currency) }}</td>
								<td class="tx-num" :class="{ 'tx-danger': i.status === 'Overdue' }">{{ fmtMoney(i.outstanding_amount, i.currency) }}</td>
								<td><Badge :status="i.status" /></td>
								<td><a :href="downloadUrl('account.invoice_pdf', { name: i.name })" class="tx-iconbtn" :aria-label="state.t('account.pdf')" @click.stop>
									<Icon name="download" size="16" /></a></td>
							</tr>
						</tbody>
					</table>
				</div>
			</div>

			<!-- Statement -->
			<div v-else-if="tab === 'statement'">
				<div class="tx-stats">
					<div v-for="s in statement.totals" :key="s.currency" class="tx-stat" :class="{ 'tx-stat--danger': s.overdue > 0 }">
						<span class="tx-stat__n tx-stat__n--money">{{ fmtMoney(s.outstanding, s.currency) }}</span>
						<span>{{ state.t("account.outstanding") }} · {{ s.currency }}</span>
						<small v-if="s.overdue">{{ state.t("account.overdue") }}: {{ fmtMoney(s.overdue, s.currency) }} ({{ s.overdue_count }})</small>
					</div>
					<Empty v-if="!statement.totals.length" icon="check" />
				</div>
				<div class="tx-card tx-card--flush">
					<div class="tx-card__head tx-pad"><h2>{{ state.t("account.payments") }}</h2></div>
					<Empty v-if="!statement.recent_payments.length" icon="receipt" />
					<div v-for="p in statement.recent_payments" :key="p.name" class="tx-row">
						<span class="tx-row__main"><strong>{{ fmtMoney(p.paid_amount, p.currency) }}</strong>
							<small>{{ fmtDate(p.posting_date) }} · {{ p.mode_of_payment || "" }} {{ p.reference_no ? "· " + p.reference_no : "" }}</small></span>
					</div>
				</div>
			</div>

			<!-- Documents -->
			<div v-else-if="tab === 'documents'" class="tx-card tx-card--flush">
				<Empty v-if="!documents.length" icon="file" />
				<div v-for="d in documents" :key="d.name" class="tx-row">
					<span class="tx-row__main">
						<strong>{{ d.title }}</strong>
						<small>{{ d.category }} · {{ d.file_name }}<template v-if="d.remaining !== null"> · {{ d.remaining }} {{ state.t("account.remaining") }}</template></small>
						<small v-if="d.description" class="tx-muted">{{ d.description }}</small>
					</span>
					<a :href="downloadUrl('documents.download', { grant: d.name })" class="tx-btn tx-btn--ghost tx-btn--sm">
						<Icon name="download" size="16" />{{ state.t("common.download") }}</a>
				</div>
			</div>
		</Loader>

		<div v-if="doc" class="tx-modal" role="dialog" aria-modal="true" @click.self="doc = null">
			<div class="tx-card tx-modal__body tx-modal__body--wide">
				<div class="tx-card__head">
					<h2 class="tx-mono">{{ doc.name }}</h2>
					<Badge :status="doc.status" />
				</div>
				<table class="tx-table">
					<thead><tr><th>{{ state.t("account.items") }}</th><th class="tx-num">{{ state.t("account.qty") }}</th>
						<th class="tx-num">{{ state.t("account.rate") }}</th><th class="tx-num">{{ state.t("account.amount") }}</th></tr></thead>
					<tbody>
						<tr v-for="(it, i) in doc.items" :key="i">
							<td>{{ it.item_name }}</td><td class="tx-num">{{ it.qty }} {{ it.uom }}</td>
							<td class="tx-num">{{ fmtMoney(it.rate, doc.currency) }}</td><td class="tx-num">{{ fmtMoney(it.amount, doc.currency) }}</td>
						</tr>
					</tbody>
					<tfoot>
						<tr v-if="doc.total_taxes_and_charges"><td colspan="3">{{ state.t("account.tax") }}</td>
							<td class="tx-num">{{ fmtMoney(doc.total_taxes_and_charges, doc.currency) }}</td></tr>
						<tr><td colspan="3"><strong>{{ state.t("common.total") }}</strong></td>
							<td class="tx-num"><strong>{{ fmtMoney(doc.grand_total, doc.currency) }}</strong></td></tr>
						<tr v-if="doc.outstanding_amount !== undefined"><td colspan="3">{{ state.t("account.outstanding") }}</td>
							<td class="tx-num">{{ fmtMoney(doc.outstanding_amount, doc.currency) }}</td></tr>
					</tfoot>
				</table>
				<div class="tx-formactions">
					<a v-if="docKind === 'invoice'" :href="downloadUrl('account.invoice_pdf', { name: doc.name })" class="tx-btn tx-btn--ghost">
						<Icon name="download" size="16" />{{ state.t("account.pdf") }}</a>
					<a v-if="state.modules.services" :href="queryLink" data-nav class="tx-btn tx-btn--ghost">{{ state.t("account.query") }}</a>
					<button class="tx-btn tx-btn--primary" @click="doc = null">{{ state.t("common.close") }}</button>
				</div>
			</div>
		</div>
	</section>
</template>

<script setup>
import { computed, onMounted, ref } from "vue";
import { call, downloadUrl } from "../api";
import { link, route } from "../router";
import { state, can, fmtDate, fmtMoney, toast } from "../store";
import Icon from "../components/Icon.vue";
import { Badge, Empty, Loader } from "../components/ui";

const tabs = computed(() => [
	{ id: "orders", label: "account.orders", cap: "orders.read" },
	{ id: "invoices", label: "account.invoices", cap: "invoices.read" },
	{ id: "statement", label: "account.statement", cap: "statements.read" },
	{ id: "documents", label: "account.documents", cap: "documents.read", module: "documents" },
].filter((t) => can(t.cap) && (!t.module || state.modules[t.module])));

const tab = ref(tabs.value.some((t) => t.id === route.query.tab) ? route.query.tab : tabs.value[0]?.id);
const orders = ref([]);
const invoices = ref([]);
const statement = ref({ totals: [], recent_payments: [] });
const documents = ref([]);
const onlyOutstanding = ref(false);
const loading = ref(true);
const error = ref("");
const doc = ref(null);
const docKind = ref("");

const queryLink = computed(() => {
	const dt = docKind.value === "invoice" ? "Sales Invoice" : "Sales Order";
	return link(`services?ref_doctype=${encodeURIComponent(dt)}&ref_name=${encodeURIComponent(doc.value?.name || "")}`);
});

async function load() {
	if (!tab.value) {
		loading.value = false;
		return;
	}
	loading.value = true;
	error.value = "";
	try {
		if (tab.value === "orders") orders.value = await call("account.orders", { page_length: 50 });
		if (tab.value === "invoices")
			invoices.value = await call("account.invoices", { page_length: 50, only_outstanding: onlyOutstanding.value ? 1 : 0 });
		if (tab.value === "statement") statement.value = await call("account.statement");
		if (tab.value === "documents") documents.value = await call("documents.list_documents");
	} catch (e) {
		error.value = e.message;
	} finally {
		loading.value = false;
	}
}

function switchTab(id) {
	tab.value = id;
	load();
}

async function openDoc(kind, name) {
	try {
		docKind.value = kind;
		doc.value = await call(kind === "order" ? "account.order" : "account.invoice", { name });
	} catch (e) {
		toast(e.message, "error");
	}
}

onMounted(load);
</script>
