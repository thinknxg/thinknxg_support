// Standalone API client for the chat widget (works on website pages without the portal store).
const BASE = "/api/method/thinknxg_support.api.v1.livechat.";

function csrf() {
	const boot = window.thinknxg_support_boot || {};
	return boot.csrf_token || (window.frappe && window.frappe.csrf_token) || window.csrf_token || "";
}

function serverMessage(body) {
	try {
		if (body._server_messages) {
			return JSON.parse(body._server_messages)
				.map((m) => {
					try {
						return JSON.parse(m).message;
					} catch (e) {
						return m;
					}
				})
				.map((h) => {
					const d = document.createElement("div");
					d.innerHTML = h;
					return d.textContent;
				})
				.join(" ");
		}
	} catch (e) {
		/* ignore */
	}
	return null;
}

export class ChatError extends Error {
	constructor(message, status) {
		super(message);
		this.status = status;
	}
}

export async function chatCall(method, params = {}, { post = false, files = [], token = null } = {}) {
	const headers = { Accept: "application/json" };
	const token_ = csrf();
	if (token_ && token_ !== "None") headers["X-Frappe-CSRF-Token"] = token_;
	if (token) headers["X-Support-Chat-Token"] = token;
	let url = BASE + method;
	let body;
	const clean = Object.fromEntries(Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== ""));
	if (post) {
		if (files.length) {
			body = new FormData();
			Object.entries(clean).forEach(([k, v]) => body.append(k, v));
			files.forEach((f) => body.append("file", f, f.name));
		} else {
			headers["Content-Type"] = "application/json";
			body = JSON.stringify(clean);
		}
	} else {
		const q = new URLSearchParams(clean).toString();
		if (q) url += "?" + q;
	}
	let res;
	try {
		res = await fetch(url, { method: post ? "POST" : "GET", headers, body, credentials: "same-origin" });
	} catch (e) {
		throw new ChatError("network", 0);
	}
	let data = {};
	try {
		data = await res.json();
	} catch (e) {
		/* non-json */
	}
	if (!res.ok) throw new ChatError(serverMessage(data) || "error", res.status);
	return data.message;
}

export function newId() {
	if (window.crypto && window.crypto.randomUUID) return window.crypto.randomUUID();
	return "c-" + Date.now().toString(36) + Math.random().toString(36).slice(2, 10);
}

const KEY = "thinknxg_support:chat";
export const session = {
	get() {
		try {
			return JSON.parse(window.localStorage.getItem(KEY) || "null");
		} catch (e) {
			return null;
		}
	},
	set(v) {
		try {
			window.localStorage.setItem(KEY, JSON.stringify(v));
		} catch (e) {
			/* storage unavailable: chat still works for this page view */
		}
	},
	clear() {
		try {
			window.localStorage.removeItem(KEY);
		} catch (e) {
			/* ignore */
		}
	},
};

export function textToHtml(text) {
	const esc = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
	return String(text || "").trim().split(/\n{2,}/).map((p) => `<p>${esc(p).replace(/\n/g, "<br>")}</p>`).join("");
}
