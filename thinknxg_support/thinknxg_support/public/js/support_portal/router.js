// Minimal history router for the portal base path (default /thinkdesk), no extra dependency.
import { reactive } from "vue";
import { state } from "./store";

export const ROUTES = [
	{ name: "dashboard", pattern: "" },
	{ name: "ticket-new", pattern: "tickets/new" },
	{ name: "ticket", pattern: "tickets/:id" },
	{ name: "tickets", pattern: "tickets" },
	{ name: "conversation", pattern: "conversations/:id" },
	{ name: "conversations", pattern: "conversations" },
	{ name: "article", pattern: "knowledge/:id" },
	{ name: "knowledge", pattern: "knowledge" },
	{ name: "services", pattern: "services" },
	{ name: "account", pattern: "account" },
	{ name: "settings", pattern: "settings" },
];

export const route = reactive({ name: "dashboard", params: {}, query: {} });

function resolve() {
	const base = state.base.replace(/\/$/, "");
	let path = window.location.pathname;
	if (path.startsWith(base)) path = path.slice(base.length);
	path = path.replace(/^\/+|\/+$/g, "");
	const parts = path ? path.split("/") : [];
	let matched = null;
	for (const r of ROUTES) {
		const pp = r.pattern ? r.pattern.split("/") : [];
		if (pp.length !== parts.length) continue;
		const params = {};
		const ok = pp.every((seg, i) => {
			if (seg.startsWith(":")) {
				params[seg.slice(1)] = decodeURIComponent(parts[i]);
				return true;
			}
			return seg === parts[i];
		});
		if (ok) {
			matched = { name: r.name, params };
			break;
		}
	}
	const query = Object.fromEntries(new URLSearchParams(window.location.search));
	route.name = matched ? matched.name : "not-found";
	route.params = matched ? matched.params : {};
	route.query = query;
}

export function navigate(path, replace = false) {
	const target = state.base + (path ? "/" + path.replace(/^\//, "") : "");
	if (target === window.location.pathname + window.location.search) return;
	window.history[replace ? "replaceState" : "pushState"]({}, "", target);
	resolve();
	window.scrollTo(0, 0);
}

export function link(path) {
	return state.base + (path ? "/" + path.replace(/^\//, "") : "");
}

export function startRouter() {
	window.addEventListener("popstate", resolve);
	// intercept in-app anchor clicks
	document.addEventListener("click", (e) => {
		const a = e.target.closest && e.target.closest("a[data-nav]");
		if (!a || e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
		e.preventDefault();
		const href = a.getAttribute("href") || "";
		navigate(href.startsWith(state.base) ? href.slice(state.base.length) : href);
	});
	resolve();
}
