<template>
	<section>
		<div class="tx-pagehead">
			<h1>{{ state.t("conv.title") }}</h1>
			<button class="tx-btn tx-btn--primary" @click="startNew"><Icon name="plus" size="16" />{{ state.t("conv.new") }}</button>
		</div>

		<div class="tx-inbox" :class="{ 'tx-inbox--thread': activeId || composing }">
			<div class="tx-inbox__list tx-card tx-card--flush">
				<Loader :loading="loadingList" :error="listError" @retry="loadList">
					<Empty v-if="!list.length" icon="chat" />
					<a v-for="c in list" :key="c.name" :href="link('conversations/' + c.name)" data-nav class="tx-convitem"
						:class="{ on: c.name === activeId }">
						<span class="tx-row__main">
							<strong>{{ c.subject }}</strong>
							<small><template v-if="c.channel && c.channel !== 'Portal'">{{ c.channel }} · </template>{{ fmtDate(c.last_activity_at, true) }}<template v-if="c.helpdesk_ticket"> · #{{ c.helpdesk_ticket }}</template></small>
						</span>
						<span v-if="c.unread" class="tx-count">{{ c.unread }}</span>
						<Badge v-else :status="c.status" />
					</a>
				</Loader>
			</div>

			<div class="tx-inbox__thread tx-card">
				<form v-if="composing" class="tx-form" @submit.prevent="create">
					<button type="button" class="tx-backlink tx-only-sm" @click="composing = false"><Icon name="back" size="16" />{{ state.t("common.back") }}</button>
					<h2>{{ state.t("conv.new") }}</h2>
					<label class="tx-field"><span>{{ state.t("conv.subject") }}</span>
						<input v-model="newSubject" required maxlength="140" /></label>
					<label class="tx-field"><span>{{ state.t("conv.message") }}</span>
						<textarea v-model="newMessage" rows="6" required maxlength="20000"></textarea></label>
					<label v-if="can('conversations.organization')" class="tx-check">
						<input v-model="shareOrg" type="checkbox" /> {{ state.t("conv.share_org") }}</label>
					<FilePicker v-model="files" :max="1" />
					<div class="tx-formactions">
						<button type="button" class="tx-btn tx-btn--ghost" @click="composing = false">{{ state.t("common.cancel") }}</button>
						<button class="tx-btn tx-btn--primary" :disabled="busy">{{ state.t("conv.start") }}</button>
					</div>
				</form>

				<template v-else-if="activeId">
					<Loader :loading="loadingThread && !thread" :error="threadError" @retry="loadThread">
						<template v-if="thread">
							<header class="tx-thread__head">
								<a :href="link('conversations')" data-nav class="tx-backlink tx-only-sm"><Icon name="back" size="16" /></a>
								<div>
									<h2>{{ thread.conversation.subject }}</h2>
									<small class="tx-muted">
										<template v-if="state.provider === 'Raven'">{{ state.t("conv.provider_raven") }}</template>
										<a v-if="thread.conversation.helpdesk_ticket" :href="link('tickets/' + thread.conversation.helpdesk_ticket)" data-nav>
											· {{ state.t("conv.escalated") }} #{{ thread.conversation.helpdesk_ticket }}</a>
									</small>
								</div>
								<div class="tx-actions">
									<button v-if="state.modules.tickets && !thread.conversation.helpdesk_ticket && thread.conversation.status !== 'Closed'"
										class="tx-btn tx-btn--ghost tx-btn--sm" :disabled="busy" @click="escalate">{{ state.t("conv.escalate") }}</button>
									<button v-if="thread.conversation.status !== 'Closed'" class="tx-btn tx-btn--ghost tx-btn--sm"
										:disabled="busy" @click="close">{{ state.t("conv.close") }}</button>
								</div>
							</header>
							<div ref="scroller" class="tx-thread" aria-live="polite">
								<article v-for="m in thread.messages" :key="m.id" class="tx-bubble"
									:class="m.from_customer ? 'tx-bubble--me' : 'tx-bubble--them'">
									<small>{{ m.is_me ? state.t("tickets.you") : m.author }} · {{ fmtDate(m.created, true) }}</small>
									<div class="tx-prose" v-html="m.content"></div>
									<a v-if="m.has_attachment" :href="downloadUrl('conversations.download_attachment', { message: m.id })" class="tx-chip">
										<Icon name="paperclip" size="14" />{{ m.attachment_name }}</a>
								</article>
							</div>
							<p v-if="thread.conversation.status === 'Closed'" class="tx-muted tx-pad">{{ state.t("conv.closed") }}</p>
							<form v-else class="tx-composer" @submit.prevent="send">
								<textarea v-model="draft" rows="2" :placeholder="state.t('conv.type_message')"
									:aria-label="state.t('conv.type_message')" maxlength="20000" @keydown.enter.exact.prevent="send"></textarea>
								<div class="tx-composer__bar">
									<FilePicker v-model="files" :max="1" />
									<button class="tx-btn tx-btn--primary" :disabled="busy || (!draft.trim() && !files.length)">{{ state.t("common.send") }}</button>
								</div>
							</form>
						</template>
					</Loader>
				</template>
				<Empty v-else icon="chat" :text="state.t('conv.empty')" />
			</div>
		</div>
	</section>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from "vue";
import { call, downloadUrl, uuid } from "../api";
import { link, navigate, route } from "../router";
import { state, can, fmtDate, toast } from "../store";
import { textToHtml } from "../text";
import Icon from "../components/Icon.vue";
import { Badge, Empty, FilePicker, Loader } from "../components/ui";

const list = ref([]);
const loadingList = ref(true);
const listError = ref("");
const thread = ref(null);
const loadingThread = ref(false);
const threadError = ref("");
const draft = ref("");
const files = ref([]);
const busy = ref(false);
const composing = ref(route.query.new === "1");
const newSubject = ref("");
const newMessage = ref("");
const shareOrg = ref(false);
const scroller = ref(null);
let pendingId = null; // reused on retry so the server can de-duplicate
let poll;

const activeId = computed(() => (route.name === "conversation" ? route.params.id : null));

async function loadList() {
	loadingList.value = true;
	listError.value = "";
	try {
		list.value = await call("conversations.list_conversations");
	} catch (e) {
		listError.value = e.message;
	} finally {
		loadingList.value = false;
	}
}

async function loadThread(silent = false) {
	if (!activeId.value) return;
	if (!silent) loadingThread.value = true;
	threadError.value = "";
	try {
		const before = thread.value?.messages.length;
		thread.value = await call("conversations.get_messages", { conversation: activeId.value });
		const item = list.value.find((c) => c.name === activeId.value);
		if (item && item.unread) {
			state.unreadMessages = Math.max(0, state.unreadMessages - item.unread);
			item.unread = 0;
		}
		if (before !== thread.value.messages.length) scrollDown();
	} catch (e) {
		if (!silent) threadError.value = e.message;
	} finally {
		loadingThread.value = false;
	}
}

function scrollDown() {
	nextTick(() => scroller.value && (scroller.value.scrollTop = scroller.value.scrollHeight));
}

function startNew() {
	composing.value = true;
	if (activeId.value) navigate("conversations?new=1");
}

async function create() {
	busy.value = true;
	pendingId = pendingId || uuid();
	try {
		const r = await call("conversations.start_conversation", {
			subject: newSubject.value, message: textToHtml(newMessage.value),
			visibility: shareOrg.value ? "Organization" : "Participant", client_message_id: pendingId,
		}, { post: true, files: files.value });
		pendingId = null;
		composing.value = false;
		newSubject.value = newMessage.value = "";
		files.value = [];
		await loadList();
		navigate("conversations/" + r.name, true);
	} catch (e) {
		toast(e.message, "error");
	} finally {
		busy.value = false;
	}
}

async function send() {
	if (busy.value || (!draft.value.trim() && !files.value.length)) return;
	busy.value = true;
	pendingId = pendingId || uuid();
	try {
		await call("conversations.send_message", {
			conversation: activeId.value, message: textToHtml(draft.value), client_message_id: pendingId,
		}, { post: true, files: files.value });
		pendingId = null;
		draft.value = "";
		files.value = [];
		await loadThread(true);
	} catch (e) {
		toast(e.message, "error");
	} finally {
		busy.value = false;
	}
}

async function escalate() {
	busy.value = true;
	try {
		const r = await call("conversations.escalate", { conversation: activeId.value }, { post: true });
		toast(`${state.t("conv.escalated")} #${r.ticket}`);
		await loadThread(true);
	} catch (e) {
		toast(e.message, "error");
	} finally {
		busy.value = false;
	}
}

async function close() {
	busy.value = true;
	try {
		await call("conversations.close", { conversation: activeId.value }, { post: true });
		await Promise.all([loadThread(true), loadList()]);
	} catch (e) {
		toast(e.message, "error");
	} finally {
		busy.value = false;
	}
}

onMounted(() => {
	loadList();
	if (activeId.value) loadThread();
	poll = setInterval(() => !document.hidden && activeId.value && loadThread(true), 10000);
});
onBeforeUnmount(() => clearInterval(poll));
</script>
