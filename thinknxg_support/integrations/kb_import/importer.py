"""Help-article importer: read a source, rebrand each article into a proposal, publish approved ones.

Nothing is published automatically. Every article carries the source's attribution, and a source must
have its licence confirmed before its articles can be published.
"""
from __future__ import annotations

import hashlib
import html as html_lib
import re
import time
from urllib.parse import quote, urljoin, urlparse

import frappe
import requests
from bs4 import BeautifulSoup
from frappe import _
from frappe.utils import cint, now_datetime

from thinknxg_support.audit import log_event
from thinknxg_support.integrations import capabilities, helpdesk
from thinknxg_support.integrations.kb_import import rebrand
from thinknxg_support.utils import clean_html

SRC = "Support Knowledge Source"
IMP = "Support Article Import"
UA = "thinkNXG-KB-Importer/1.0 (+{site})"
PAUSE = 0.4  # seconds between requests to the source


class SourceError(Exception):
    pass


# ------------------------------------------------------------------ fetching
class Client:
    def __init__(self, src):
        self.src = src
        self.base = (src.base_url or "").rstrip("/")
        self.s = requests.Session()
        self.s.headers["User-Agent"] = UA.format(site=frappe.utils.get_url())
        self.s.headers["Accept"] = "application/json"
        if src.auth_method == "API Key" and src.api_key:
            self.s.headers["Authorization"] = f"token {src.api_key}:{src.get_password('api_secret', raise_exception=False)}"
        self._logged_in = False

    def login(self):
        if self.src.auth_method != "Login" or self._logged_in:
            return
        r = self.s.post(self.base + "/api/method/login", timeout=30,
                        data={"usr": self.src.username, "pwd": self.src.get_password("password", raise_exception=False)})
        if r.status_code >= 400:
            raise SourceError(_("Login to the source failed (HTTP {0}).").format(r.status_code))
        self._logged_in = True

    def get(self, path, params=None, raw=False):
        self.login()
        url = path if path.startswith("http") else self.base + path
        time.sleep(PAUSE)
        try:
            r = self.s.get(url, params=params, timeout=45)
        except requests.RequestException as e:
            raise SourceError(f"{e.__class__.__name__} for {url}")
        if r.status_code in (401, 403):
            raise SourceError(_("The source refused access (HTTP {0}). Set up access with an account on that site.").format(r.status_code))
        if r.status_code >= 400:
            raise SourceError(f"HTTP {r.status_code} for {url}")
        if raw:
            return r
        try:
            data = r.json()
        except ValueError:
            raise SourceError(_("The source did not return JSON for {0}.").format(url))
        return data.get("message", data.get("data", data))


def _cat_fields(c):
    if isinstance(c, str):
        return c, c
    return (c.get("name") or c.get("category_id") or c.get("category"),
            c.get("category_name") or c.get("title") or c.get("name"))


def helpdesk_articles(src, client=None):
    """Yield dicts: id, title, html, category, modified. Tries the Helpdesk knowledge-base API, then REST."""
    client = client or Client(src)
    wanted = {x.strip().lower() for x in (src.only_categories or "").splitlines() if x.strip()}
    count, limit = 0, cint(src.max_articles) or 500
    try:
        cats = client.get("/api/method/helpdesk.api.knowledge_base.get_categories") or []
        listing = []
        for c in cats:
            cid, label = _cat_fields(c)
            if not cid or (wanted and (label or "").lower() not in wanted and str(cid).lower() not in wanted):
                continue
            arts = client.get("/api/method/helpdesk.api.knowledge_base.get_category_articles", {"category": cid}) or []
            for a in arts:
                aid = a.get("name") if isinstance(a, dict) else a
                if aid:
                    listing.append((aid, label))
        fetch = lambda aid: client.get("/api/method/helpdesk.api.knowledge_base.get_article", {"name": aid})  # noqa: E731
    except SourceError as first:
        if "refused access" in str(first):
            raise
        arts = client.get("/api/resource/HD Article", {
            "fields": '["name","title","category","modified"]', "filters": '[["status","=","Published"]]',
            "limit_page_length": limit})
        labels = {}
        try:
            for c in client.get("/api/resource/HD Article Category", {"fields": '["name","category_name"]',
                                                                      "limit_page_length": 1000}) or []:
                labels[c["name"]] = c.get("category_name") or c["name"]
        except SourceError:
            pass
        listing = [(a["name"], labels.get(a.get("category"), a.get("category"))) for a in arts
                   if not wanted or (labels.get(a.get("category"), "") or "").lower() in wanted]
        fetch = lambda aid: client.get(f"/api/resource/HD Article/{quote(str(aid))}")  # noqa: E731
    for aid, label in listing:
        if count >= limit:
            break
        a = fetch(aid) or {}
        if isinstance(a, dict) and isinstance(a.get("article"), dict):
            a = a["article"]
        title = a.get("title") or a.get("subject")
        body = a.get("content") or a.get("description") or ""
        if not title or not body:
            continue
        count += 1
        yield {"id": str(aid), "title": title, "html": body, "category": label or _("General"),
               "modified": str(a.get("modified") or "")}


def page_articles(src, client=None):
    client = client or Client(src)
    for line in (src.page_urls or "").splitlines()[: cint(src.max_articles) or 500]:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        cat, url = (x.strip() for x in line.split("|", 1)) if "|" in line else (_("General"), line)
        if not url.startswith(("https://", "http://")):
            continue
        r = client.get(url, raw=True)
        text = r.text
        if url.endswith(".md") or "markdown" in r.headers.get("Content-Type", ""):
            title, body = _from_markdown(text)
        else:
            title, body = _from_html(text, url)
        if title and body:
            yield {"id": url, "title": title, "html": body, "category": cat, "modified": r.headers.get("Last-Modified", ""),
                   "url": url}


def _from_markdown(text):
    text = re.sub(r"^---\n.*?\n---\n", "", text, flags=re.S)  # front matter
    m = re.search(r"^#\s+(.+)$", text, re.M)
    title = m.group(1).strip() if m else None
    if m:
        text = text[:m.start()] + text[m.end():]
    return title, frappe.utils.md_to_html(text)


def _from_html(text, url):
    soup = BeautifulSoup(text, "html.parser")
    main = soup.find("article") or soup.find("main") or soup.body
    if not main:
        return None, None
    for bad in main.find_all(["nav", "header", "footer", "aside", "script", "style", "form"]):
        bad.decompose()
    h1 = main.find("h1")
    title = h1.get_text(" ", strip=True) if h1 else (soup.title.get_text(strip=True) if soup.title else None)
    if h1:
        h1.decompose()
    for tag in main.find_all(src=True):
        tag["src"] = urljoin(url, tag["src"])
    for tag in main.find_all(href=True):
        tag["href"] = urljoin(url, tag["href"])
    return title, main.decode_contents()


def fetch(src):
    if src.source_type == "Page URLs":
        return page_articles(src)
    return helpdesk_articles(src)


# ------------------------------------------------------------------ transform
def rules_of(src):
    rows = [(r.find, r.replace_with, r.match_case) for r in src.rules if r.enabled]
    return rebrand.compile_rules(rows or [(f, t, 1) for f, t in rebrand.DEFAULT_RULES])


def source_url(src, art) -> str:
    if art.get("url"):
        return art["url"]
    if src.article_url_pattern:
        return src.article_url_pattern.format(base_url=src.base_url, id=quote(str(art["id"])))
    return src.help_center_url or src.base_url


def attribution(src, original_title, url) -> str:
    text = (src.attribution_template or "").format(
        source_title=original_title, source_url=url, owner=src.owner_name or "", licence=src.licence or "",
        licence_url=src.licence_url or "")
    esc = html_lib.escape(text)
    for link in {url, src.licence_url}:
        if link:
            e = html_lib.escape(link)
            esc = esc.replace(e, f'<a href="{e}" target="_blank" rel="noopener">{e}</a>', 1)
    return f'<hr><p class="tx-attribution"><small>{esc}</small></p>'


def transform(src, art, compiled=None):
    compiled = compiled or rules_of(src)
    title, n1 = rebrand.rebrand_text(art["title"], compiled)
    body = clean_html(art["html"], max_len=2000000)
    body, n2 = rebrand.rebrand_html(body, compiled)
    category, _n = rebrand.rebrand_text(art.get("category") or "", compiled)
    flags = rebrand.review_flags(art["html"])
    if re.search(r"<img\b", body) and not src.download_images:
        flags.append("Images load from the source site")
    return {"title": title[:140], "html": body, "category": category[:140] or _("General"), "replacements": n1 + n2,
            "flags": flags}


def _hash(art) -> str:
    return hashlib.sha256((art["title"] + "\n" + art["html"]).encode()).hexdigest()


# ------------------------------------------------------------------ run
def run(source: str, user: str | None = None):
    src = frappe.get_doc(SRC, source)
    if not src.enabled:
        return
    stats = {"new": 0, "changed": 0, "same": 0, "errors": 0}
    compiled = rules_of(src)
    frappe.db.set_value(SRC, source, {"last_run_status": _("Running…"), "last_run_on": now_datetime()})
    frappe.db.commit()
    try:
        for art in fetch(src):
            try:
                _store(src, art, compiled, stats)
                frappe.db.commit()
            except Exception as e:
                frappe.db.rollback()
                stats["errors"] += 1
                frappe.log_error(title=f"thinkNXG KB import: {art.get('id')}", message=str(e))
    except SourceError as e:
        msg = _("Stopped: {0}").format(e)
        frappe.db.set_value(SRC, source, "last_run_status", msg)
        log_event("Integration Error", severity="Warning", reference_doctype=SRC, reference_name=source,
                  details=str(e)[:300], user=user or "Administrator")
        frappe.db.commit()
        return msg
    msg = _("{new} new proposals, {changed} changed at the source, {same} unchanged, {errors} errors.").format(**stats)
    frappe.db.set_value(SRC, source, "last_run_status", msg)
    frappe.db.commit()
    if user:
        frappe.publish_realtime("msgprint", {"message": msg, "title": _("Help article import")}, user=user)
    return msg


def _store(src, art, compiled, stats):
    h = _hash(art)
    name = frappe.db.get_value(IMP, {"source": src.name, "source_id": art["id"]})
    t = transform(src, art, compiled)
    values = {"proposed_title": t["title"], "proposed_html": t["html"], "category_name": t["category"],
              "replacements": t["replacements"], "review_notes": "\n".join("- " + f for f in t["flags"]) or None,
              "original_title": art["title"], "original_html": art["html"], "original_hash": h,
              "source_category": art.get("category"), "source_modified": art.get("modified"),
              "source_url": source_url(src, art)}
    if not name:
        frappe.get_doc({"doctype": IMP, "source": src.name, "source_id": art["id"],
                        "status": "Needs Review" if t["flags"] else "Proposed", **values}).insert(ignore_permissions=True)
        stats["new"] += 1
        return
    doc = frappe.get_doc(IMP, name)
    if doc.original_hash == h:
        stats["same"] += 1
        return
    if doc.status in ("Published", "Approved"):
        values["status"] = "Source Changed"
    elif doc.status != "Rejected":
        values["status"] = "Needs Review" if t["flags"] else "Proposed"
    doc.update(values)
    doc.save(ignore_permissions=True)
    stats["changed"] += 1


def reapply(source: str):
    src = frappe.get_doc(SRC, source)
    compiled = rules_of(src)
    for name in frappe.get_all(IMP, filters={"source": source, "status": ["in", ["Proposed", "Needs Review"]]},
                               pluck="name"):
        doc = frappe.get_doc(IMP, name)
        t = transform(src, {"id": doc.source_id, "title": doc.original_title, "html": doc.original_html,
                            "category": doc.source_category}, compiled)
        doc.update({"proposed_title": t["title"], "proposed_html": t["html"], "category_name": t["category"],
                    "replacements": t["replacements"], "review_notes": "\n".join("- " + f for f in t["flags"]) or None})
        doc.save(ignore_permissions=True)
        frappe.db.commit()


def test(source: str) -> str:
    src = frappe.get_doc(SRC, source)
    try:
        items = []
        for art in fetch(src):
            items.append(art)
            if len(items) >= 3:
                break
    except SourceError as e:
        return _("Could not read the source: {0}").format(frappe.utils.escape_html(str(e)))
    if not items:
        return _("Connected, but no published articles were found.")
    compiled = rules_of(src)
    rows = "".join(f"<li><b>{frappe.utils.escape_html(transform(src, a, compiled)['title'])}</b> "
                   f"<small>({frappe.utils.escape_html(a['title'])})</small></li>" for a in items)
    return _("Connected. First articles, rebranded (original in brackets):") + f"<ul>{rows}</ul>"


# ------------------------------------------------------------------ publish
def _target(src) -> str:
    if src.target == "Helpdesk" or (src.target == "Automatic" and helpdesk.kb_available()):
        if not helpdesk.kb_available():
            frappe.throw(_("Helpdesk is not available. Choose the thinkDesk knowledge base as the target."))
        return "HD Article"
    return "Support Knowledge Article"


def _category(target: str, label: str) -> str | None:
    label = (label or _("General"))[:140]
    if target == "HD Article":
        if not frappe.db.exists("DocType", "HD Article Category"):
            return None
        name = frappe.db.get_value("HD Article Category", {"category_name": label})
        if not name:
            name = frappe.get_doc({"doctype": "HD Article Category", "category_name": label}).insert(ignore_permissions=True).name
        return name
    if not frappe.db.exists("Support Knowledge Category", label):
        frappe.get_doc({"doctype": "Support Knowledge Category", "category_name": label}).insert(ignore_permissions=True)
    return label


def _download_images(html: str, src) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for img in soup.find_all("img", src=True):
        url = img["src"]
        if url.startswith("/") and src.base_url:
            url = src.base_url + url
        if not url.startswith(("https://", "http://")) or urlparse(url).netloc == urlparse(frappe.utils.get_url()).netloc:
            continue
        try:
            r = requests.get(url, timeout=30, headers={"User-Agent": UA.format(site=frappe.utils.get_url())})
            ctype = r.headers.get("Content-Type", "").split(";")[0]
            if r.status_code != 200 or not ctype.startswith("image/") or len(r.content) > 5 * 1024 * 1024:
                continue
            fname = (urlparse(url).path.rsplit("/", 1)[-1] or "image")[:100]
            f = frappe.get_doc({"doctype": "File", "file_name": fname, "content": r.content, "is_private": 0})
            f.flags.ignore_permissions = True
            f.insert()
            img["src"] = f.file_url
        except Exception:
            continue
    return str(soup)


def _rewrite_links(html: str, src, mapping: dict) -> str:
    """Links to the source site: point them at the imported copy, keep them, or drop the link but keep the text."""
    hosts = {urlparse(u).netloc for u in (src.base_url, src.help_center_url) if u}
    hosts.discard("")
    if not hosts or src.link_policy == "Keep":
        return html
    from thinknxg_support.constants import PORTAL_ROUTE

    soup = BeautifulSoup(html, "html.parser")
    for a in soup.find_all("a", href=True):
        u = urlparse(a["href"])
        if u.netloc not in hosts:
            continue
        last = u.path.rstrip("/").rsplit("/", 1)[-1]
        target = mapping.get(last)
        if target and src.link_policy == "Point to imported article when possible":
            a["href"] = f"{PORTAL_ROUTE}/knowledge/{target}"
            a.attrs.pop("target", None)
        elif src.link_policy == "Remove link, keep text":
            a.unwrap()
    return str(soup)


def publish_many(names: list[str]) -> str:
    done, skipped = 0, []
    for name in names:
        try:
            publish_one(name)
            done += 1
            frappe.db.commit()
        except frappe.ValidationError as e:
            frappe.db.rollback()
            skipped.append(f"{name}: {e}")
    msg = _("{0} articles published.").format(done)
    if skipped:
        msg += "<br>" + _("Not published:") + "<ul>" + "".join(f"<li>{frappe.utils.escape_html(s)}</li>" for s in skipped[:20]) + "</ul>"
    return msg


def publish_one(name: str):
    imp = frappe.get_doc(IMP, name)
    if imp.status == "Rejected":
        frappe.throw(_("Rejected proposals cannot be published."))
    src = frappe.get_doc(SRC, imp.source)
    if not src.licence_confirmed:
        frappe.throw(_("Confirm the licence on source {0} before publishing its articles.").format(src.name))
    target = imp.target_doctype or _target(src)
    mapping = {r.source_id: r.target_name for r in frappe.get_all(
        IMP, filters={"source": src.name, "target_name": ["is", "set"]}, fields=["source_id", "target_name"])}
    body = clean_html(imp.proposed_html or "", max_len=2000000)
    if src.download_images:
        body = _download_images(body, src)
    body = _rewrite_links(body, src, mapping)
    body += attribution(src, imp.original_title, imp.source_url)
    category = _category(target, imp.category_name)
    if target == "HD Article":
        af = capabilities.get().get("helpdesk", {}).get("article_fields", {})
        values = {"title": imp.proposed_title, "content": body}
        if category and af.get("category"):
            values["category"] = category
        if af.get("status"):
            values["status"] = "Published"
        elif af.get("published"):
            values["published"] = 1
    else:
        values = {"title": imp.proposed_title, "content": body, "category": category, "status": "Published",
                  "audience": src.audience or "Everyone", "source_url": imp.source_url,
                  "source_title": imp.original_title, "licence": src.licence, "imported_from": imp.name}
    if imp.target_name and frappe.db.exists(target, imp.target_name):
        doc = frappe.get_doc(target, imp.target_name)
        doc.update(values)
        doc.save(ignore_permissions=True)
    else:
        doc = frappe.get_doc({"doctype": target, **values}).insert(ignore_permissions=True)
    imp.db_set({"status": "Published", "target_doctype": target, "target_name": doc.name, "published_on": now_datetime()})
    log_event("Administrative Change", reference_doctype=IMP, reference_name=imp.name,
              details={"published": f"{target} {doc.name}"})
    return doc.name


def preview(name: str) -> str:
    imp = frappe.get_doc(IMP, name)
    notes = "".join(f"<li>{frappe.utils.escape_html(n.lstrip('- '))}</li>" for n in (imp.review_notes or "").splitlines() if n.strip())
    return (
        '<div style="display:grid;grid-template-columns:1fr 1fr;gap:16px">'
        f'<div><div class="text-muted small mb-1">{_("Original")}: {frappe.utils.escape_html(imp.original_title or "")}</div>'
        f'<div style="border:1px solid var(--border-color);border-radius:8px;padding:12px;max-height:520px;overflow:auto">{clean_html(imp.original_html or "", max_len=2000000)}</div></div>'
        f'<div><div class="text-muted small mb-1">{_("Proposed")}: {frappe.utils.escape_html(imp.proposed_title or "")} '
        f'· {_("{0} names replaced").format(imp.replacements or 0)}</div>'
        f'<div style="border:1px solid var(--border-color);border-radius:8px;padding:12px;max-height:520px;overflow:auto">{clean_html(imp.proposed_html or "", max_len=2000000)}</div></div>'
        "</div>"
        + (f'<div class="mt-3"><b>{_("Check before publishing")}</b><ul>{notes}</ul></div>' if notes else "")
    )
