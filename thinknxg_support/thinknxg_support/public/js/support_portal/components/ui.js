// Small presentational components shared across views (render functions, no template compiler needed).
import { h, ref } from "vue";
import Icon from "./Icon.vue";
import { state, fmtSize, toast } from "../store";

const STATUS_TONE = {
	Open: "info", Paused: "warn", Resolved: "ok", Waiting: "warn", Closed: "muted",
	"In Progress": "info", "Waiting on Customer": "warn", Completed: "ok", Cancelled: "muted", Escalated: "info",
	Paid: "ok", Unpaid: "warn", Overdue: "danger", "Partly Paid": "warn", Return: "muted", "Credit Note Issued": "muted",
	"To Deliver and Bill": "info", "To Bill": "warn", "To Deliver": "info",
	Active: "ok", "Past Due Date": "danger", Delivered: "ok",
};

export const Badge = {
	props: { status: String, label: String, tone: String },
	setup(props) {
		return () =>
			h("span", { class: ["tx-badge", `tx-badge--${props.tone || STATUS_TONE[props.status] || "muted"}`] },
				props.label || props.status || "");
	},
};

export const Empty = {
	props: { icon: { type: String, default: "file" }, text: String },
	setup(props, { slots }) {
		return () => h("div", { class: "tx-empty" }, [
			h(Icon, { name: props.icon, size: 28 }),
			h("p", props.text || state.t("common.none")),
			slots.default && slots.default(),
		]);
	},
};

/** <Loader :loading :error @retry> wraps async content. */
export const Loader = {
	props: { loading: Boolean, error: String },
	emits: ["retry"],
	setup(props, { slots, emit }) {
		return () => {
			if (props.error)
				return h("div", { class: "tx-error", role: "alert" }, [
					h(Icon, { name: "alert" }),
					h("span", props.error),
					h("button", { class: "tx-btn tx-btn--ghost", onClick: () => emit("retry") }, state.t("common.retry")),
				]);
			if (props.loading) return h("div", { class: "tx-loading" }, [h("div", { class: "tx-spinner" })]);
			return slots.default ? slots.default() : null;
		};
	},
};

/** File picker that validates extension and size client-side (server re-validates). */
export const FilePicker = {
	props: { modelValue: { type: Array, default: () => [] }, max: { type: Number, default: 5 } },
	emits: ["update:modelValue"],
	setup(props, { emit }) {
		const input = ref(null);
		const allowed = () => (state.extensions || "").split(",").map((e) => e.trim().toLowerCase()).filter(Boolean);
		function onChange(e) {
			const picked = Array.from(e.target.files || []);
			const ok = [];
			for (const f of picked) {
				const ext = (f.name.split(".").pop() || "").toLowerCase();
				if (allowed().length && !allowed().includes(ext)) {
					toast(`.${ext} — ${state.t("errors.forbidden")}`, "error");
					continue;
				}
				if (f.size > state.maxMb * 1024 * 1024) {
					toast(`${f.name} > ${state.maxMb} MB`, "error");
					continue;
				}
				ok.push(f);
			}
			emit("update:modelValue", [...props.modelValue, ...ok].slice(0, props.max));
			e.target.value = "";
		}
		function remove(i) {
			const next = props.modelValue.slice();
			next.splice(i, 1);
			emit("update:modelValue", next);
		}
		return () => h("div", { class: "tx-files" }, [
			h("input", { ref: input, type: "file", multiple: true, hidden: true, onChange,
				accept: allowed().map((e) => "." + e).join(",") }),
			h("button", { type: "button", class: "tx-btn tx-btn--ghost tx-btn--sm", onClick: () => input.value.click() },
				[h(Icon, { name: "paperclip", size: 16 }), state.t("common.attach")]),
			...props.modelValue.map((f, i) => h("span", { class: "tx-chip" }, [
				`${f.name} · ${fmtSize(f.size)}`,
				h("button", { type: "button", class: "tx-chip__x", "aria-label": state.t("common.close"), onClick: () => remove(i) },
					h(Icon, { name: "x", size: 14 })),
			])),
		]);
	},
};
