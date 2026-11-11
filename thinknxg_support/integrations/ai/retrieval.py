"""Knowledge index: published Helpdesk and thinkDesk knowledge articles and Knowledge Snippets, split into passages.

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


def sources(only=None):
    """Yield (doctype, name, title, text, audience, route) for everything that should be indexed.

    only=(doctype, name) limits it to one document (used when a single source changes)."""
    conf = s()

    def want(doctype):
        return only is None or only[0] == doctype

    def flt(base):
        return {**base, "name": only[1]} if only else base

    hd = capabilities.get().get("helpdesk", {})
    if conf.index_helpdesk_articles and hd.get("article_doctype") and want("HD Article"):
        af = hd.get("article_fields", {})
        filters = {"status": "Published"} if af.get("status") else ({"published": 1} if af.get("published") else {})
        for a in frappe.get_all("HD Article", filters=flt(filters), fields=["name", "title", "content"], limit=5000):
            yield "HD Article", a.name, a.title, _html_text(a.content), "Everyone", f"knowledge/{a.name}"
    if conf.index_helpdesk_articles and want("Support Knowledge Article") \
            and frappe.db.exists("DocType", "Support Knowledge Article"):
        for a in frappe.get_all("Support Knowledge Article", filters=flt({"status": "Published"}),
                                fields=["name", "title", "content", "audience"], limit=10000):
            yield ("Support Knowledge Article", a.name, a.title, _html_text(a.content), a.audience or "Everyone",
                   f"knowledge/{a.name}")
    if conf.index_snippets and want("Support Knowledge Snippet"):
        for n in frappe.get_all("Support Knowledge Snippet", filters=flt({"enabled": 1}),
                                fields=["name", "question", "answer", "audience", "link"], limit=5000):
            yield "Support Knowledge Snippet", n.name, n.question, _html_text(n.answer), n.audience or "Everyone", n.link
    # 1.11: uploaded documents (private files: no link is cited) and crawled website pages
    if conf.get("index_documents") and want("Support Knowledge Document") \
            and frappe.db.exists("DocType", "Support Knowledge Document"):
        for d in frappe.get_all("Support Knowledge Document", filters=flt({"enabled": 1, "status": "Ready"}),
                                fields=["name", "title", "extracted_text", "audience"], limit=10000):
            yield "Support Knowledge Document", d.name, d.title, d.extracted_text or "", d.audience or "Staff", None
    if conf.get("index_websites") and want("Support Knowledge Web Page") \
            and frappe.db.exists("DocType", "Support Knowledge Web Page"):
        sites = {w.name: w for w in frappe.get_all("Support Knowledge Website", filters={"enabled": 1},
                                                   fields=["name", "audience"])}
        if sites:
            for p in frappe.get_all("Support Knowledge Web Page",
                                    filters=flt({"status": "Active", "website": ["in", list(sites)]}),
                                    fields=["name", "title", "text", "url", "website"], limit=20000):
                yield ("Support Knowledge Web Page", p.name, p.title, p.text or "", sites[p.website].audience or "Everyone",
                       p.url)


BOOST = {"High": 1.25, "Normal": 1.0, "Low": 0.8}


def boost_of(doctype: str, name: str) -> float:
    """The source's priority as a ranking weight. It orders matches; it never lets a weak match through."""
    conf = s()
    if doctype in ("HD Article", "Support Knowledge Article"):
        level = conf.get("priority_articles")
    elif doctype == "Support Knowledge Snippet":
        level = conf.get("priority_snippets")
    elif doctype == "Support Knowledge Document":
        level = frappe.db.get_value(doctype, name, "priority")
    elif doctype == "Support Knowledge Web Page":
        site = frappe.db.get_value(doctype, name, "website")
        level = frappe.db.get_value("Support Knowledge Website", site, "priority") if site else None
    else:
        level = None
    return BOOST.get(level or "Normal", 1.0)


def overview() -> list[dict]:
    """One row per knowledge source, for Support AI Settings: what it is, whether it is used, how much is indexed."""
    conf = s()
    counts = {d: frappe.db.count(CHUNK, {"source_doctype": d}) for d in (
        "HD Article", "Support Knowledge Article", "Support Knowledge Snippet", "Support Knowledge Document")}
    rows = []

    def add(label, kind, on, items, passages, **kw):
        state = "Off" if not on else kw.pop("state", None) or ("Active" if passages else "Empty")
        rows.append({"label": label, "type": kind, "state": state, "items": items, "passages": passages if on else 0,
                     "priority": kw.pop("priority", "Normal"), "last": kw.pop("last", None), **kw})

    hd = capabilities.get().get("helpdesk", {})
    articles = 0
    if frappe.db.exists("DocType", "Support Knowledge Article"):
        articles += frappe.db.count("Support Knowledge Article", {"status": "Published"})
    if hd.get("article_doctype"):
        articles += frappe.db.count("HD Article")
    add("Knowledge base articles", "Knowledge Base", conf.index_helpdesk_articles, articles,
        counts.get("HD Article", 0) + counts.get("Support Knowledge Article", 0),
        priority=conf.get("priority_articles") or "Normal", last=conf.last_indexed_on,
        detail="Published Helpdesk and thinkDesk articles")
    add("Knowledge snippets", "Knowledge Base", conf.index_snippets,
        frappe.db.count("Support Knowledge Snippet", {"enabled": 1}), counts.get("Support Knowledge Snippet", 0),
        priority=conf.get("priority_snippets") or "Normal", last=conf.last_indexed_on,
        route="/app/support-knowledge-snippet", detail="Short questions and answers")
    if frappe.db.exists("DocType", "Support Knowledge Document"):
        D = "Support Knowledge Document"
        failed = frappe.db.count(D, {"status": "Failed"})
        add("Uploaded documents", "Uploaded Files", conf.get("index_documents"),
            frappe.db.count(D, {"enabled": 1, "status": "Ready"}), counts.get(D, 0), route="/app/support-knowledge-document",
            priority="Per document",
            last=(frappe.get_all(D, filters={"status": "Ready"}, order_by="processed_on desc", limit=1,
                                 pluck="processed_on") or [None])[0],
            errors=failed, note=f"{failed} file(s) could not be read" if failed else "",
            detail="PDF, Word, Excel, CSV, text, Markdown and HTML files")
    if frappe.db.exists("DocType", "Support Knowledge Website"):
        W, P = "Support Knowledge Website", "Support Knowledge Web Page"
        per_site = {r.website: r.n for r in frappe.db.sql(
            f"""select p.website, count(c.name) as n from `tab{P}` p join `tab{CHUNK}` c
                on c.source_doctype = %s and c.source_name = p.name group by p.website""", (P,), as_dict=True)}
        for w in frappe.get_all(W, fields=["name", "enabled", "start_url", "priority", "page_count", "last_crawl_on",
                                           "crawl_state", "error_count", "last_crawl_status"], order_by="creation asc"):
            working = w.crawl_state in ("Queued", "Crawling")
            state = "Working" if working else "Problem" if w.crawl_state == "Failed" else None
            add(w.name, "Website", conf.get("index_websites") and w.enabled, w.page_count or 0, per_site.get(w.name, 0),
                state=state, priority=w.priority or "Normal", last=w.last_crawl_on, detail=w.start_url,
                route=f"/app/support-knowledge-website/{frappe.utils.quote(w.name)}", errors=w.error_count or 0,
                note=(w.last_crawl_status or "")[:160] if (working or w.error_count or w.crawl_state == "Failed")
                else (w.crawl_state or "Never crawled"))
    return rows


def _index_one(doctype, name, title, text, audience, route, existing: dict):
    conf = s()
    boost = boost_of(doctype, name)
    pieces = split(title or name, text, int(conf.chunk_size or 900))
    model = conf.embedding_model if conf.use_embeddings else None
    want = []
    for i, piece in enumerate(pieces):
        key = f"{audience}|{route}|{model}|{piece}" + (f"|{boost}" if boost != 1.0 else "")
        h = hashlib.sha256(key.encode()).hexdigest()
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
            "audience": audience, "route": route, "content": piece, "content_hash": h, "embedding_model": model, "boost": boost,
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
    row = next(iter(sources(only=(doctype, name))), None)
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
                                      "embedding", "embedding_model", "boost"], limit=50000)
        rows = [dict(r) for r in rows]
        frappe.cache.set_value(key, rows, expires_in_sec=3600)
    return rows


def search(query: str, audience: str = "Everyone", k: int | None = None) -> list[dict]:
    """audience: Everyone (guests), Customers (verified customers; also sees Everyone) or Staff (the agent copilot:
    sees everything, including staff-only documents)."""
    conf = s()
    k = int(k or conf.top_k or 4)
    audiences = {"Customers": ("Everyone", "Customers"),
                 "Staff": ("Everyone", "Customers", "Staff")}.get(audience, ("Everyone",))
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
    # Only matches that reach the minimum relevance on their own count; among those, preferred sources come first.
    floor = float(conf.min_relevance or 0)
    scored = [(score, r) for score, r in scored if score >= floor]
    scored.sort(key=lambda x: (x[0] * float(x[1].get("boost") or 1.0), x[0]), reverse=True)
    out, per_source = [], {}
    for score, r in scored:
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
