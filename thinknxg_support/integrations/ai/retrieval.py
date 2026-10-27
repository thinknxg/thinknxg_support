"""Knowledge index: published Helpdesk articles and Knowledge Snippets, split into passages.

Search uses cosine similarity over stored embeddings when configured, otherwise keyword overlap.
Audience is enforced on every search: guests only ever get "Everyone" passages.
"""
from __future__ import annotations

import array
import base64
import hashlib
import math
import re
import uuid

import frappe
from frappe.utils import now_datetime, strip_html

from thinknxg_support.integrations import capabilities

CHUNK = "Support Knowledge Chunk"
WORD = re.compile(r"[\w؀-ۿ]+", re.UNICODE)
STOP = set("""a an and are as at be by can do does for from has have how i if in is it its me my of on or our
please the this to was we what when where which who why will with you your hi hello thanks
في من على إلى عن هل ما ماذا كيف متى أين هذا هذه أن إن انا أنا لي مع""".split())


def s():
    return frappe.get_cached_doc("Support AI Settings")


# ------------------------------------------------------------------ vectors
def pack(vec) -> str:
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return base64.b64encode(array.array("f", [x / norm for x in vec]).tobytes()).decode()


def unpack(text: str):
    a = array.array("f")
    a.frombytes(base64.b64decode(text))
    return a


def tokens(text: str) -> list[str]:
    return [w for w in (m.group(0).casefold() for m in WORD.finditer(text or "")) if w not in STOP and len(w) > 1]


# ------------------------------------------------------------------ chunking
def split(title: str, text: str, size: int) -> list[str]:
    text = re.sub(r"[ \t]+", " ", text or "").strip()
    paras = [p.strip() for p in re.split(r"\n\s*\n|\n", text) if p.strip()]
    out, cur = [], ""
    for p in paras:
        while len(p) > size:
            out.append(p[:size])
            p = p[size:]
        if len(cur) + len(p) + 1 > size and cur:
            out.append(cur)
            cur = p
        else:
            cur = f"{cur}\n{p}" if cur else p
    if cur:
        out.append(cur)
    return [f"{title}\n{c}" for c in out] or [title]


def _html_text(html: str) -> str:
    html = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</h\d>", "\n", html or "")
    return strip_html(html)


def sources():
    """Yield (doctype, name, title, text, audience, route) for everything that should be indexed."""
    conf = s()
    hd = capabilities.get().get("helpdesk", {})
    if conf.index_helpdesk_articles and hd.get("article_doctype"):
        af = hd.get("article_fields", {})
        filters = {"status": "Published"} if af.get("status") else ({"published": 1} if af.get("published") else {})
        for a in frappe.get_all("HD Article", filters=filters, fields=["name", "title", "content"], limit=5000):
            yield "HD Article", a.name, a.title, _html_text(a.content), "Everyone", f"knowledge/{a.name}"
    if conf.index_snippets:
        for n in frappe.get_all("Support Knowledge Snippet", filters={"enabled": 1},
                                fields=["name", "question", "answer", "audience", "link"], limit=5000):
            yield "Support Knowledge Snippet", n.name, n.question, _html_text(n.answer), n.audience or "Everyone", n.link


def _index_one(doctype, name, title, text, audience, route, existing: dict):
    conf = s()
    pieces = split(title or name, text, int(conf.chunk_size or 900))
    model = conf.embedding_model if conf.use_embeddings else None
    want = []
    for i, piece in enumerate(pieces):
        h = hashlib.sha256(f"{audience}|{route}|{model}|{piece}".encode()).hexdigest()
        want.append((i, piece, h))
    keep = {h for _i, _p, h in want if h in existing}
    for h, cname in existing.items():
        if h not in keep:
            frappe.delete_doc(CHUNK, cname, ignore_permissions=True, force=True)
    todo = [(i, p, h) for i, p, h in want if h not in keep]
    vectors = []
    if todo and model:
        from thinknxg_support.integrations.ai import providers

        vectors = providers.embed([p for _i, p, _h in todo])
    for k, (i, piece, h) in enumerate(todo):
        frappe.get_doc({
            "doctype": CHUNK, "source_doctype": doctype, "source_name": name, "title": title, "chunk_index": i,
            "audience": audience, "route": route, "content": piece, "content_hash": h, "embedding_model": model,
            "embedding": pack(vectors[k]) if vectors else None,
        }).insert(ignore_permissions=True)
    return len(todo)


def _existing(doctype, name) -> dict:
    return {r.content_hash: r.name for r in frappe.get_all(
        CHUNK, filters={"source_doctype": doctype, "source_name": name}, fields=["name", "content_hash"])}


def rebuild():
    """Re-index everything. Unchanged passages are kept, so re-runs are cheap."""
    seen, added, errors = set(), 0, []
    frappe.db.set_single_value("Support AI Settings", "index_status", "Indexing…")
    frappe.db.commit()
    for doctype, name, title, text, audience, route in sources():
        seen.add((doctype, name))
        try:
            added += _index_one(doctype, name, title, text, audience, route, _existing(doctype, name))
            frappe.db.commit()
        except Exception as e:
            frappe.db.rollback()
            errors.append(f"{doctype} {name}: {str(e)[:120]}")
            if len(errors) > 20:
                break
    for row in frappe.get_all(CHUNK, fields=["name", "source_doctype", "source_name"], limit=100000):
        if (row.source_doctype, row.source_name) not in seen:
            frappe.delete_doc(CHUNK, row.name, ignore_permissions=True, force=True)
    count = frappe.db.count(CHUNK)
    status = f"{count} passages from {len(seen)} documents; {added} updated."
    if errors:
        status += " Errors: " + "; ".join(errors[:5])
    frappe.db.set_single_value("Support AI Settings", {"index_status": status, "chunk_count": count,
                                                       "last_indexed_on": now_datetime()})
    bump_version()
    frappe.db.commit()
    return status


def index_source(doctype: str, name: str):
    row = next((x for x in sources() if x[0] == doctype and x[1] == name), None)
    if not row:
        frappe.db.delete(CHUNK, {"source_doctype": doctype, "source_name": name})
    else:
        try:
            _index_one(*row, _existing(doctype, name))
        except Exception:
            frappe.log_error(title="thinkNXG Support: knowledge indexing failed")
    frappe.db.set_single_value("Support AI Settings", "chunk_count", frappe.db.count(CHUNK))
    bump_version()


def on_article_change(doc, method=None):
    if frappe.db.get_single_value("Support AI Settings", "index_helpdesk_articles"):
        frappe.enqueue(index_source, queue="long", enqueue_after_commit=True, doctype=doc.doctype, name=doc.name)


def daily_refresh():
    if frappe.db.get_single_value("Support AI Settings", "enable_ai"):
        rebuild()


def bump_version():
    frappe.cache.set_value("thinknxg_support:kb_version", uuid.uuid4().hex)


# ------------------------------------------------------------------ search
def _corpus(audiences: tuple):
    version = frappe.cache.get_value("thinknxg_support:kb_version") or "0"
    key = f"thinknxg_support:kb:{version}:{'+'.join(audiences)}"
    rows = frappe.cache.get_value(key)
    if rows is None:
        rows = frappe.get_all(CHUNK, filters={"audience": ["in", list(audiences)]},
                              fields=["name", "source_doctype", "source_name", "title", "route", "content",
                                      "embedding", "embedding_model"], limit=50000)
        rows = [dict(r) for r in rows]
        frappe.cache.set_value(key, rows, expires_in_sec=3600)
    return rows


def search(query: str, audience: str = "Everyone", k: int | None = None) -> list[dict]:
    """audience: Everyone (guests) or Customers (verified customers; also sees Everyone)."""
    conf = s()
    k = int(k or conf.top_k or 4)
    audiences = ("Everyone", "Customers") if audience == "Customers" else ("Everyone",)
    rows = _corpus(audiences)
    if not rows or not (query or "").strip():
        return []
    scored = []
    model = conf.embedding_model if conf.use_embeddings else None
    if model and any(r.get("embedding") and r.get("embedding_model") == model for r in rows):
        from thinknxg_support.integrations.ai import providers

        qv = unpack(pack(providers.embed([query])[0]))
        for r in rows:
            if r.get("embedding") and r.get("embedding_model") == model:
                v = unpack(r["embedding"])
                scored.append((sum(a * b for a, b in zip(qv, v)), r))
    else:
        q = set(tokens(query))
        if not q:
            return []
        for r in rows:
            words = set(tokens(r["content"]))
            title = set(tokens(r["title"]))
            if not (q & (words | title)):
                continue
            hit = sum(1.0 if t in words else 0 for t in q) + sum(0.5 for t in q if t in title)
            scored.append((min(1.0, hit / (len(q) * 1.0)), r))
    scored.sort(key=lambda x: x[0], reverse=True)
    out, per_source = [], {}
    for score, r in scored:
        if score < float(conf.min_relevance or 0):
            break
        key = (r["source_doctype"], r["source_name"])
        if per_source.get(key, 0) >= 2:
            continue
        per_source[key] = per_source.get(key, 0) + 1
        out.append({"id": f"S{len(out) + 1}", "score": round(float(score), 3), "title": r["title"],
                    "content": r["content"], "route": r["route"], "doctype": r["source_doctype"],
                    "name": r["source_name"]})
        if len(out) >= k:
            break
    return out
