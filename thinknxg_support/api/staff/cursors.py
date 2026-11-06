"""Opaque, stable pagination cursors: (timestamp, name) of the last row returned."""
import base64
import json


def encode(t: str, n: str) -> str:
    return base64.urlsafe_b64encode(json.dumps({"t": t, "n": n}, separators=(",", ":")).encode()).decode().rstrip("=")


def decode(cursor: str | None):
    if not cursor:
        return None
    try:
        pad = "=" * (-len(cursor) % 4)
        d = json.loads(base64.urlsafe_b64decode(cursor + pad).decode())
        return {"t": str(d["t"]), "n": str(d["n"])}
    except Exception:
        import frappe

        frappe.throw(frappe._("Invalid cursor."))
