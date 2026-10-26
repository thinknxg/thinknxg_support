<template>
	<section class="tx-narrow">
		<div class="tx-pagehead"><h1>{{ state.t("settings.title") }}</h1></div>

		<Loader :loading="loading" :error="error" @retry="load">
			<form class="tx-card tx-form" @submit.prevent="saveProfile">
				<h2>{{ state.t("settings.profile") }}</h2>
				<p class="tx-muted">{{ profile.full_name }} · {{ profile.email }}</p>
				<div class="tx-formrow">
					<label class="tx-field"><span>{{ state.t("settings.language") }}</span>
						<select v-model="profile.language"><option value="en">English</option><option value="ar">العربية</option></select>
					</label>
					<label class="tx-field"><span>{{ state.t("settings.theme") }}</span>
						<select v-model="profile.theme"><option>System</option><option>Light</option><option>Dark</option></select>
					</label>
				</div>
				<div class="tx-formrow">
					<label class="tx-field"><span>{{ state.t("settings.timezone") }}</span>
						<select v-model="profile.time_zone">
							<option value="">—</option>
							<option v-for="z in zones" :key="z" :value="z">{{ z }}</option>
						</select>
					</label>
					<label v-if="state.orgs.length > 1" class="tx-field"><span>{{ state.t("settings.default_org") }}</span>
						<select v-model="profile.default_customer">
							<option v-for="o in state.orgs" :key="o.customer" :value="o.customer">{{ o.customer_name }}</option>
						</select>
					</label>
				</div>
				<div class="tx-formactions"><button class="tx-btn tx-btn--primary" :disabled="busy">{{ state.t("common.save") }}</button></div>
			</form>

			<form class="tx-card tx-form" @submit.prevent="savePrefs">
				<h2>{{ state.t("settings.notifications") }}</h2>
				<label v-for="k in PREF_KEYS" :key="k" class="tx-check">
					<input v-model="prefs[k]" type="checkbox" :true-value="1" :false-value="0" /> {{ state.t("settings." + k) }}
				</label>
				<div class="tx-formactions"><button class="tx-btn tx-btn--primary" :disabled="busy">{{ state.t("common.save") }}</button></div>
			</form>

			<div v-if="can('members.read')" class="tx-card">
				<h2>{{ state.t("settings.members") }}</h2>
				<div v-for="m in members" :key="m.user + m.access_level" class="tx-row">
					<span class="tx-row__main"><strong>{{ m.full_name || m.user }}</strong><small>{{ m.user }}</small></span>
					<Badge :label="m.access_level" :tone="m.enabled ? 'info' : 'muted'" />
				</div>
				<form v-if="can('members.request')" class="tx-form tx-mt" @submit.prevent="requestMember">
					<h3>{{ state.t("settings.request_member") }}</h3>
					<div class="tx-formrow">
						<label class="tx-field"><span>{{ state.t("settings.member_name") }}</span><input v-model="member.full_name" required maxlength="140" /></label>
						<label class="tx-field"><span>{{ state.t("settings.member_email") }}</span><input v-model="member.email" type="email" required /></label>
						<label class="tx-field"><span>{{ state.t("settings.member_level") }}</span>
							<select v-model="member.access_level"><option>Self</option><option>Billing</option><option>Service</option></select></label>
					</div>
					<div class="tx-formactions"><button class="tx-btn tx-btn--ghost" :disabled="busy">{{ state.t("common.submit") }}</button></div>
				</form>
			</div>
		</Loader>
	</section>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { call } from "../api";
import { state, can, setLang, setOrg, toast } from "../store";
import { Badge, Loader } from "../components/ui";

const PREF_KEYS = ["portal_ticket_updates", "email_ticket_updates", "portal_message_alerts", "email_message_alerts",
	"email_request_updates", "email_invoice_alerts"];
const profile = ref({});
const prefs = ref({});
const members = ref([]);
const member = ref({ full_name: "", email: "", access_level: "Self" });
const loading = ref(true);
const error = ref("");
const busy = ref(false);
const zones = (() => {
	try {
		return Intl.supportedValuesOf("timeZone");
	} catch (e) {
		return ["Asia/Muscat", "Asia/Dubai", "Asia/Riyadh", "Asia/Qatar", "Asia/Bahrain", "Asia/Kuwait", "Asia/Kolkata", "Europe/London", "UTC"];
	}
})();

async function load() {
	loading.value = true;
	error.value = "";
	try {
		[profile.value, prefs.value] = await Promise.all([
			call("profile.get_profile", {}, { org: false }),
			call("notifications.get_preferences", {}, { org: false }),
		]);
		profile.value.theme = profile.value.theme || "System";
		if (can("members.read")) members.value = await call("account.members");
	} catch (e) {
		error.value = e.message;
	} finally {
		loading.value = false;
	}
}

async function saveProfile() {
	busy.value = true;
	try {
		const p = await call("profile.update_profile", {
			language: profile.value.language, theme: profile.value.theme, time_zone: profile.value.time_zone || "",
			default_customer: profile.value.default_customer || "",
		}, { post: true, org: false });
		setLang(p.language);
		document.documentElement.dataset.theme = (p.theme || "System").toLowerCase();
		if (p.default_customer) setOrg(p.default_customer);
		toast(state.t("common.saved"));
	} catch (e) {
		toast(e.message, "error");
	} finally {
		busy.value = false;
	}
}

async function savePrefs() {
	busy.value = true;
	try {
		prefs.value = await call("notifications.update_preferences", prefs.value, { post: true, org: false });
		toast(state.t("common.saved"));
	} catch (e) {
		toast(e.message, "error");
	} finally {
		busy.value = false;
	}
}

async function requestMember() {
	busy.value = true;
	try {
		await call("account.request_member", member.value, { post: true });
		member.value = { full_name: "", email: "", access_level: "Self" };
		toast(state.t("settings.member_requested"));
	} catch (e) {
		toast(e.message, "error");
	} finally {
		busy.value = false;
	}
}

onMounted(load);
</script>
