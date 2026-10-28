<template>
	<section class="tx-narrow">
		<a :href="link('tickets')" data-nav class="tx-backlink"><Icon name="back" size="16" />{{ state.t("tickets.title") }}</a>
		<h1>{{ state.t("tickets.new") }}</h1>

		<form class="tx-card tx-form" @submit.prevent="submit">
			<label class="tx-field">
				<span>{{ state.t("tickets.subject") }}</span>
				<input v-model="subject" required minlength="3" maxlength="140" autocomplete="off" @input="suggest" />
			</label>

			<div v-if="suggestions.length" class="tx-suggest" aria-live="polite">
				<p><Icon name="book" size="16" />{{ state.t("tickets.suggested") }}</p>
				<a v-for="a in suggestions" :key="a.name" :href="link('knowledge/' + a.name)" target="_blank" rel="noopener">
					{{ a.title }}
				</a>
			</div>

			<div class="tx-formrow">
				<label v-if="opts.ticket_types.length" class="tx-field">
					<span>{{ state.t("tickets.type") }}</span>
					<select v-model="ticketType">
						<option value="">—</option>
						<option v-for="t in opts.ticket_types" :key="t" :value="t">{{ t }}</option>
					</select>
				</label>
				<label v-if="opts.priorities.length" class="tx-field">
					<span>{{ state.t("tickets.priority") }}</span>
					<select v-model="priority">
						<option value="">—</option>
						<option v-for="p in opts.priorities" :key="p" :value="p">{{ p }}</option>
					</select>
				</label>
			</div>

			<label class="tx-field">
				<span>{{ state.t("tickets.description") }}</span>
				<textarea v-model="description" rows="8" required maxlength="20000"></textarea>
			</label>

			<FilePicker v-model="files" />

			<p v-if="error" class="tx-error" role="alert">{{ error }}</p>
			<div class="tx-formactions">
				<a :href="link('tickets')" data-nav class="tx-btn tx-btn--ghost">{{ state.t("common.cancel") }}</a>
				<button class="tx-btn tx-btn--primary" :disabled="busy">{{ state.t("tickets.create") }}</button>
			</div>
		</form>
	</section>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { call } from "../api";
import { link, navigate, route } from "../router";
import { state, toast } from "../store";
import { textToHtml } from "../text";
import Icon from "../components/Icon.vue";
import { FilePicker } from "../components/ui";

// Opened from a help article ("Raise a ticket"): start with its title and link.
const subject = ref((route.query.subject || "").slice(0, 140));
const description = ref(route.query.article ? state.t("kb.ticket_about") + " " + route.query.article + "\n\n" : "");
const ticketType = ref("");
const priority = ref("");
const files = ref([]);
const busy = ref(false);
const error = ref("");
const opts = ref({ ticket_types: [], priorities: [] });
const suggestions = ref([]);
let timer;

function suggest() {
	clearTimeout(timer);
	if (!state.modules.knowledge || subject.value.length < 4) {
		suggestions.value = [];
		return;
	}
	timer = setTimeout(async () => {
		try {
			suggestions.value = await call("knowledge.search", { q: subject.value, limit: 4 }, { org: false });
		} catch (e) {
			suggestions.value = [];
		}
	}, 400);
}

async function submit() {
	busy.value = true;
	error.value = "";
	try {
		const r = await call(
			"tickets.create_ticket",
			{ subject: subject.value, description: textToHtml(description.value), ticket_type: ticketType.value,
				priority: priority.value },
			{ post: true, files: files.value }
		);
		toast(`${state.t("tickets.created")} #${r.ticket}`);
		navigate("tickets/" + r.ticket, true);
	} catch (e) {
		error.value = e.message;
	} finally {
		busy.value = false;
	}
}

onMounted(async () => {
	try {
		opts.value = await call("tickets.options");
	} catch (e) {
		/* options are optional */
	}
});
</script>
