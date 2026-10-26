<template>
	<section>
		<a :href="link('tickets')" data-nav class="tx-backlink"><Icon name="back" size="16" />{{ state.t("tickets.title") }}</a>
		<Loader :loading="loading" :error="error" @retry="load">
			<template v-if="t">
				<div class="tx-pagehead">
					<div>
						<p class="tx-eyebrow tx-mono">#{{ t.name }}</p>
						<h1>{{ t.subject }}</h1>
					</div>
					<Badge :status="t.overdue ? 'Overdue' : t.status_category" :label="t.status" />
				</div>

				<div class="tx-detail">
					<div class="tx-detail__main">
						<article class="tx-msg tx-msg--me">
							<header><strong>{{ t.is_mine ? state.t("tickets.you") : "" }}</strong><small>{{ fmtDate(t.opened_on, true) }}</small></header>
							<div class="tx-prose" v-html="t.description"></div>
						</article>

						<h2 class="tx-h2">{{ state.t("tickets.timeline") }}</h2>
						<article v-for="m in t.timeline" :key="m.id" class="tx-msg"
							:class="m.from_customer ? 'tx-msg--me' : 'tx-msg--them'">
							<header>
								<strong>{{ m.is_me ? state.t("tickets.you") : m.author }}</strong>
								<small>{{ fmtDate(m.created, true) }}</small>
							</header>
							<div class="tx-prose" v-html="m.content"></div>
							<div v-if="m.attachments.length" class="tx-attach">
								<a v-for="f in m.attachments" :key="f.name" :href="fileUrl(f)" class="tx-chip">
									<Icon name="paperclip" size="14" />{{ f.file_name }}
								</a>
							</div>
						</article>

						<form v-if="t.status_category !== 'Resolved'" class="tx-card tx-composer" @submit.prevent="send">
							<textarea v-model="reply" rows="4" :placeholder="state.t('tickets.reply')"
								:aria-label="state.t('tickets.reply')" maxlength="20000"></textarea>
							<div class="tx-composer__bar">
								<FilePicker v-model="files" />
								<button class="tx-btn tx-btn--primary" :disabled="busy || (!reply.trim() && !files.length)">
									{{ state.t("tickets.send_reply") }}
								</button>
							</div>
						</form>

						<div v-if="t.can_rate" class="tx-card tx-rate">
							<h3>{{ state.t("tickets.rate") }}</h3>
							<div class="tx-stars" role="radiogroup">
								<button v-for="n in 5" :key="n" type="button" role="radio" :aria-checked="stars === n"
									:class="{ on: n <= stars }" @click="stars = n"><Icon name="star" size="22" /></button>
							</div>
							<textarea v-model="comment" rows="2" :placeholder="state.t('tickets.rate_comment')"></textarea>
							<button class="tx-btn tx-btn--primary" :disabled="!stars || busy" @click="rate">{{ state.t("common.submit") }}</button>
						</div>
						<p v-else-if="t.rating" class="tx-muted"><Icon name="star" size="14" /> {{ t.rating }}/5 · {{ state.t("tickets.thanks") }}</p>

						<button v-if="t.can_reopen" class="tx-btn tx-btn--ghost" :disabled="busy" @click="reopen">
							{{ state.t("tickets.reopen") }}
						</button>
					</div>

					<aside class="tx-detail__side tx-card">
						<dl class="tx-meta">
							<template v-if="t.ticket_type"><dt>{{ state.t("tickets.type") }}</dt><dd>{{ t.ticket_type }}</dd></template>
							<template v-if="t.priority"><dt>{{ state.t("tickets.priority") }}</dt><dd>{{ t.priority }}</dd></template>
							<template v-if="t.team"><dt>{{ state.t("tickets.team") }}</dt><dd>{{ t.team }}</dd></template>
							<template v-if="t.response_by"><dt>{{ state.t("tickets.sla_response") }}</dt><dd>{{ fmtDate(t.response_by, true) }}</dd></template>
							<template v-if="t.resolution_by">
								<dt>{{ state.t("tickets.sla_resolution") }}</dt>
								<dd :class="{ 'tx-danger': t.overdue }">{{ fmtDate(t.resolution_by, true) }}</dd>
							</template>
						</dl>
						<div v-if="t.attachments.length">
							<h3>{{ state.t("tickets.attachments") }}</h3>
							<a v-for="f in t.attachments" :key="f.name" :href="fileUrl(f)" class="tx-filelink">
								<Icon name="download" size="14" />{{ f.file_name }} <small>{{ fmtSize(f.file_size) }}</small>
							</a>
						</div>
					</aside>
				</div>
			</template>
		</Loader>
	</section>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { call, downloadUrl } from "../api";
import { link, route } from "../router";
import { state, fmtDate, fmtSize, toast } from "../store";
import { textToHtml } from "../text";
import Icon from "../components/Icon.vue";
import { Badge, FilePicker, Loader } from "../components/ui";

const t = ref(null);
const loading = ref(true);
const error = ref("");
const reply = ref("");
const files = ref([]);
const busy = ref(false);
const stars = ref(0);
const comment = ref("");

const fileUrl = (f) => downloadUrl("tickets.download_attachment", { ticket: t.value.name, file: f.name });

async function load() {
	loading.value = true;
	error.value = "";
	try {
		t.value = await call("tickets.get_ticket", { ticket: route.params.id });
	} catch (e) {
		error.value = e.message;
	} finally {
		loading.value = false;
	}
}

async function send() {
	busy.value = true;
	try {
		t.value = await call("tickets.reply", { ticket: t.value.name, message: textToHtml(reply.value) },
			{ post: true, files: files.value });
		reply.value = "";
		files.value = [];
	} catch (e) {
		toast(e.message, "error");
	} finally {
		busy.value = false;
	}
}

async function rate() {
	busy.value = true;
	try {
		await call("tickets.rate", { ticket: t.value.name, stars: stars.value, comment: comment.value }, { post: true });
		toast(state.t("tickets.thanks"));
		await load();
	} catch (e) {
		toast(e.message, "error");
	} finally {
		busy.value = false;
	}
}

async function reopen() {
	busy.value = true;
	try {
		await call("tickets.reopen", { ticket: t.value.name }, { post: true });
		await load();
	} catch (e) {
		toast(e.message, "error");
	} finally {
		busy.value = false;
	}
}

onMounted(load);
</script>
