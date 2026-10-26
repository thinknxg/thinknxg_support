from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, getdate, nowdate

from thinknxg_support import ratelimit
from thinknxg_support.api.v1._base import context
from thinknxg_support.audit import log_event
from thinknxg_support.security import PortalAccessError, log_denied
from thinknxg_support.utils import require_module

FIELDS = ["name", "title", "category", "description", "file", "enabled", "required_capability",
          "restricted_to_user", "valid_until", "max_downloads", "download_count", "customer", "modified"]


def _usable(pu, row, customer) -> bool:
    if not row or row.customer != customer or not cint(row.enabled):
        return False
    if row.valid_until and getdate(row.valid_until) < getdate(nowdate()):
        return False
    if row.restricted_to_user and row.restricted_to_user != pu.user:
        return False
    if cint(row.max_downloads) and cint(row.download_count) >= cint(row.max_downloads):
        return False
    return pu.can(row.required_capability or "documents.read", customer)


@frappe.whitelist(methods=["GET"])
def list_documents(organization=None):
    require_module("documents")
    pu, customer = context(organization)
    rows = frappe.get_all("Support Download Grant", filters={"customer": customer, "enabled": 1}, fields=FIELDS,
                          order_by="modified desc", limit=500)
    out = []
    for r in rows:
        if _usable(pu, r, customer):
            out.append({"name": r.name, "title": r.title, "category": r.category, "description": r.description,
                        "file_name": (r.file or "").rsplit("/", 1)[-1], "modified": r.modified,
                        "remaining": (cint(r.max_downloads) - cint(r.download_count)) if cint(r.max_downloads) else None})
    return out


@frappe.whitelist(methods=["GET"])
def download(grant, organization=None):
    require_module("documents")
    pu, customer = context(organization)
    ratelimit.check("download", 60)
    row = frappe.db.get_value("Support Download Grant", grant, FIELDS, as_dict=True) if grant else None
    if not _usable(pu, row, customer):
        log_denied(pu, "Support Download Grant" if row else None, grant, "download denied")
        raise PortalAccessError(_("Document not available."))
    file_name = frappe.db.get_value("File", {"file_url": row.file, "is_private": 1})
    if not file_name:
        raise PortalAccessError(_("Document not available."))
    frappe.db.sql("update `tabSupport Download Grant` set download_count = download_count + 1 where name=%s",
                  (grant,))
    log_event("Download", reference_doctype="Support Download Grant", reference_name=grant)
    from thinknxg_support.utils import stream_file

    stream_file(file_name)
