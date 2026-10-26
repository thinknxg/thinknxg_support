// Chat widget for public website pages and the guest page /thinkdesk/chat.
// The customer portal mounts the same component itself, so pages that host the portal are skipped.
// ERPNext's own /support page is a normal website page and gets the launcher like any other.
import { createApp } from "vue";
import ChatWidget from "./support_chat/ChatWidget.vue";

const SKIP = ["/app", "/desk", "/helpdesk", "/raven"];

function mount() {
	if (window.__thinknxgChatMounted) return;
	const page = document.getElementById("support-chat-page");
	const path = window.location.pathname;
	if (!page && document.getElementById("support-app")) return; // inside the customer portal
	if (!page && SKIP.some((p) => path === p || path.startsWith(p + "/"))) return;
	window.__thinknxgChatMounted = true;
	let el = page;
	if (!el) {
		el = document.createElement("div");
		el.id = "thinknxg-support-chat";
		document.body.appendChild(el);
	}
	createApp(ChatWidget, { inline: !!page, context: page ? "page" : "website" }).mount(el);
}

if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mount);
else mount();
