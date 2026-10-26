// Thin client for the thinkNXG Support v1 API (Frappe whitelisted methods).
import { state } from "./store";

const BASE = "/api/method/thinknxg_support.api.v1.";

export class ApiError extends Error {
	constructor(message, status, type) {
		super(message);
		this.status = status;
		this.type = type;
	}
}

function buildQuery(params) {
	const q = new URLSearchParams();
	Object.entries(params || {}).forEach(([k, v]) => {
		if (v !== undefined && v !== null && v !== "") q.append(k, typeof v === "object" ? JSON.stringify(v) : v);
	});
	return q.toString();
}

function parseServerMessage(body) {
	try {
		if (body._server_messages) {
			const msgs = JSON.parse(body._server_messages).map((m) => {
				try {
					return JSON.parse(m).message;
				} catch (e) {
					return m;
				}
			});
			return msgs.map(stripTags).join("\n");
		}
	} catch (e) {
		/* ignore */
	}
	if (body.exception) return stripTags(String(body.exception).split(":").slice(1).join(":").trim());
	return null;
}

function stripTags(html) {
	const d = document.createElement("div");
	d.innerHTML = html || "";
	return d.textContent || "";
}

/**
 * call("tickets.list_tickets", { scope: "own" })
 * call("tickets.create_ticket", { subject }, { post: true, files: [File] })
 */
export async function call(method, params = {}, opts = {}) {
	const post = !!opts.post;
	const withOrg = opts.org !== false && state.org;
	const payload = { ...params };
	if (withOrg && payload.organization === undefined) payload.organization = state.org;

	const headers = { Accept: "application/json", "X-Frappe-CSRF-Token": state.csrf };
	let url = BASE + method;
	let body;

	if (post) {
		if (opts.files && opts.files.length) {
			body = new FormData();
			Object.entries(payload).forEach(([k, v]) => {
				if (v !== undefined && v !== null) body.append(k, typeof v === "object" ? JSON.stringify(v) : v);
			});
			opts.files.forEach((f) => body.append("file", f, f.name));
		} else {
			headers["Content-Type"] = "application/json";
			body = JSON.stringify(payload);
		}
	} else {
		const q = buildQuery(payload);
		if (q) url += "?" + q;
	}

	let res;
	try {
		res = await fetch(url, { method: post ? "POST" : "GET", headers, body, credentials: "same-origin" });
	} catch (e) {
		throw new ApiError(state.t("errors.network"), 0, "network");
	}

	let data = {};
	try {
		data = await res.json();
	} catch (e) {
		/* non-json */
	}
	if (!res.ok) {
		if (res.status === 401 || data.exc_type === "AuthenticationError" || data.exc_type === "SessionExpired") {
			window.location.href = "/login?redirect-to=" + encodeURIComponent(window.location.pathname);
		}
		const msg = parseServerMessage(data) || state.t(res.status === 403 ? "errors.forbidden" : "errors.generic");
		throw new ApiError(msg, res.status, data.exc_type);
	}
	return data.message;
}

/** URL for GET endpoints that stream files (cookie auth, no CSRF needed for GET). */
export function downloadUrl(method, params = {}) {
	const payload = { ...params };
	if (state.org) payload.organization = state.org;
	return BASE + method + "?" + buildQuery(payload);
}

export function uuid() {
	if (window.crypto && window.crypto.randomUUID) return window.crypto.randomUUID();
	return "m-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 10);
}
