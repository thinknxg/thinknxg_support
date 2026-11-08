"""Opaque, stable pagination cursors: (timestamp, name) of the last row returned."""
import base64
import json


def encode(t: str, n: str, p=None) -> str:
    d = {"t": t, "n": n}
    if p is not None:
        d["p"] = int(p)
    return base64.urlsafe_b64encode(json.dumps(d, separators=(",", ":")).encode()).decode().rstrip("=")


def decode(cursor: str | None):
    if not cursor:
        return None
    try:
        pad = "=" * (-len(cursor) % 4)
        d = json.loads(base64.urlsafe_b64decode(cursor + pad).decode())
        out = {"t": str(d["t"]), "n": str(d["n"])}
        if "p" in d:
            out["p"] = int(d["p"])
        return out
    except Exception:
        import frappe

        frappe.throw(frappe._("Invalid cursor."))
