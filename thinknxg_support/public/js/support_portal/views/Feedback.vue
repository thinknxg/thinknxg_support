<template>
	<section class="tx-narrow tx-feedbackpage">
		<Loader :loading="loading" :error="error" @retry="load">
			<div v-if="form" class="tx-card tx-survey">
				<template v-if="sent || form.done">
					<Icon name="check" size="28" />
					<h1>{{ state.t("fb.thanks_title") }}</h1>
					<p class="tx-muted">{{ state.t("fb.thanks") }}</p>
					<a :href="link('')" data-nav class="tx-btn">{{ state.t("nav.home") }}</a>
				</template>
				<form v-else @submit.prevent="submit">
					<h1>{{ form.title }}</h1>
					<p class="tx-muted">{{ form.intro }}<template v-if="form.agent"> ({{ form.agent }})</template></p>
					<fieldset>
						<legend>{{ state.t("fb.rate") }}</legend>
						<div class="tx-survey__stars" role="radiogroup" :aria-label="state.t('fb.rate')" @mouseleave="hover = 0">
							<button v-for="n in 5" :key="n" type="button" role="radio" :aria-checked="rating === n"
								:aria-label="n + ' – ' + form.labels[n]" :class="{ on: n <= (hover || rating) }"
								@mouseenter="hover = n" @focus="hover = n" @blur="hover = 0" @click="rating = n">★</button>
						</div>
						<small class="tx-muted">{{ (hover || rating) ? form.labels[hover || rating] : " " }}</small>
					</fieldset>
					<fieldset v-if="form.ask_resolution">
						<legend>{{ state.t("fb.resolved") }}</legend>
						<div class="tx-chips">
							<button v-for="o in ['Yes', 'Partially', 'No']" :key="o" type="button" class="tx-filter"
								:class="{ on: resolved === o }" :aria-pressed="resolved === o" @click="resolved = o">{{ state.t("fb." + o.toLowerCase()) }}</button>
						</div>
					</fieldset>
					<label v-if="form.ask_comment" class="tx-field">
						<span>{{ state.t("fb.comment") }}<template v-if="commentRequired"> *</template></span>
						<textarea v-model="comment" rows="4" maxlength="2000" :required="commentRequired"></textarea>
					</label>
					<p v-if="submitError" class="tx-error" role="alert">{{ submitError }}</p>
					<button class="tx-btn tx-btn--primary" :disabled="!canSend || sending">{{ state.t("fb.submit") }}</button>
				</form>
			</div>
		</Loader>
	</section>
</template>

<script setup>
import { computed, onMounted, ref } from "vue";
import { call } from "../api";
import { link, route } from "../router";
import { state } from "../store";
import Icon from "../components/Icon.vue";
import { Loader } from "../components/ui";

const form = ref(null);
const loading = ref(true);
const error = ref("");
const rating = ref(0);
const hover = ref(0);
const resolved = ref("");
const comment = ref("");
const sending = ref(false);
const sent = ref(false);
const submitError = ref("");
const key = () => ({ conversation: route.query.c, token: route.query.t });

const commentRequired = computed(() => !!(form.value && form.value.ask_comment && form.value.comment_required_at
	&& rating.value && rating.value <= form.value.comment_required_at));
const canSend = computed(() => rating.value > 0 && (!form.value.ask_resolution || resolved.value)
	&& (!commentRequired.value || comment.value.trim()));

async function load() {
	loading.value = true;
	error.value = "";
	try {
		form.value = await call("feedback.form", key(), { org: false });
	} catch (e) {
		error.value = e.message;
	} finally {
		loading.value = false;
	}
}

async function submit() {
	if (!canSend.value || sending.value) return;
	sending.value = true;
	submitError.value = "";
	try {
		await call("feedback.submit", { ...key(), rating: rating.value, resolved: resolved.value || null,
			comment: comment.value.trim() || null }, { post: true, org: false });
		sent.value = true;
	} catch (e) {
		submitError.value = e.message;
	} finally {
		sending.value = false;
	}
}

onMounted(load);
</script>
