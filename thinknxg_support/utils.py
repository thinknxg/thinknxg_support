"""Shared helpers: settings, sanitising, attachments, response shaping."""
from __future__ import annotations

import os

import frappe
from frappe import _
from frappe.utils import cint, cstr
from frappe.utils.html_utils import sanitize_html


def _request_cache() -> dict:
    """Per-request cache. Frappe v16 frappe.local has no __dict__."""
    store = getattr(frappe.local, "thinknxg_support_cache", None)
    if store is None:
        store = {}
        frappe.local.thinknxg_support_cache = store
    return store


def settings():
    key = "thinknxg_support_settings"
    if key not in _request_cache():
        _request_cache()[key] = frappe.get_cached_doc("Support Portal Settings")
    return _request_cache()[key]


def module_enabled(module: str) -> bool:
    return bool(cint(settings().get(f"enable_{module}")))


def require_module(module: str):
    if not module_enabled(module):
        frappe.throw(_("This feature is not enabled on the support portal."), frappe.PermissionError)


def clean_html(value: str | None, max_len: int = 20000) -> str:
    value = cstr(value).strip()
    if len(value) > max_len:
        frappe.throw(_("Message is too long."))
    return sanitize_html(value, linkify=True)


def clean_text(value: str | None, max_len: int = 500) -> str:
    value = cstr(value).strip()
    return frappe.utils.strip_html(value)[:max_len]


def allowed_extensions() -> set:
    raw = settings().allowed_attachment_extensions or ""
    return {e.strip().lower().lstrip(".") for e in raw.split(",") if e.strip()}


def validate_upload(filename: str, content: bytes):
    ext = os.path.splitext(filename or "")[1].lower().lstrip(".")
    if not ext or ext not in allowed_extensions():
        frappe.throw(_("File type .{0} is not allowed.").format(ext or "?"))
    max_mb = cint(settings().max_attachment_mb) or 10
    if len(content) > max_mb * 1024 * 1024:
        frappe.throw(_("File exceeds the {0} MB limit.").format(max_mb))
    # reject executables disguised with an allowed extension
    head = content[:4]
    if head.startswith(b"MZ") or head.startswith(b"\x7fELF"):
        frappe.throw(_("Executable files are not allowed."))


def save_private_file(filename: str, content: bytes, doctype: str, docname: str) -> dict:
    validate_upload(filename, content)
    f = frappe.get_doc(
        {
            "doctype": "File",
            "file_name": os.path.basename(filename),
            "content": content,
            "is_private": 1,
            "attached_to_doctype": doctype,
            "attached_to_name": docname,
        }
    )
    f.flags.ignore_permissions = True
    f.insert()
    return {"name": f.name, "file_name": f.file_name, "file_size": f.file_size}


def uploaded_files() -> list[tuple[str, bytes]]:
    req = getattr(frappe, "request", None)
    if not req or not getattr(req, "files", None):
        return []
    limit = cint(settings().max_attachments_per_message) or 5
    files = []
    for storage in req.files.getlist("file") or []:
        files.append((storage.filename, storage.stream.read()))
    if len(files) > limit:
        frappe.throw(_("You can attach up to {0} files at once.").format(limit))
    return files


def stream_file(file_name: str, as_download: bool = True):
    f = frappe.get_doc("File", file_name)
    frappe.local.response.filename = f.file_name
    frappe.local.response.filecontent = f.get_content()
    frappe.local.response.type = "download" if as_download else "binary"


def safe_link(url: str | None) -> bool:
    """Links configured by administrators: web addresses, site paths, mailto: and tel: only."""
    url = (url or "").strip()
    if not url or len(url) > 500 or any(c in url for c in "\n\r<>\"'`"):
        return False
    if url.startswith("/") and not url.startswith("//"):
        return True
    return url.lower().startswith(("https://", "http://", "mailto:", "tel:"))


def pick(d: dict, keys) -> dict:
    return {k: d.get(k) for k in keys}


def clear_request_cache():
    """Drop per-request memoised values (portal user, settings, schema). Used by tests and jobs."""
    for key in [k for k in list(_request_cache()) if str(k).startswith("thinknxg_support")]:
        _request_cache().pop(key, None)
