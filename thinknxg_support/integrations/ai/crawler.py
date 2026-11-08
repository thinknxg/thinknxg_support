"""1.11: read a website into the knowledge base.

Safety: only http(s); every address (and every redirect hop) must resolve to public internet addresses, so the
crawler can never reach the server's own network; robots.txt, meta robots / X-Robots-Tag noindex and nofollow are
obeyed; one site only (with or without www); pages and PDFs are size-capped; a pause between requests; no
cookies or logins. Sitemaps are read with a pattern match, not an XML parser, so no XML entities are expanded.

Pages are stored as Support Knowledge Web Page (title, text, address) and indexed like any other knowledge.
A page that disappears from the site leaves the index only after a crawl that finished its whole queue.
"""
from __future__ import annotations

import fnmatch
import hashlib
import html as htmllib
import ipaddress
import re
import socket
import time
import zlib
from collections import deque
from urllib import robotparser
from urllib.parse import parse_qsl, urldefrag, urlencode, urljoin, urlparse, urlunparse

import frappe
import requests
from frappe import _
from frappe.utils import add_to_date, cint, flt, get_datetime, now_datetime

SITE = "Support Knowledge Website"
PAGE = "Support Knowledge Web Page"
CHUNK = "Support Knowledge Chunk"
AGENT = "thinkNXG-Support-Crawler"
UA = AGENT + "/1.11 (+{site})"
MAX_PAGES = 2000
MAX_HTML = 3 * 1024 * 1024
MAX_PDF = 15 * 1024 * 1024
MIN_DELAY = 0.5
MIN_TEXT = 40
SKIP_EXT = set("jpg jpeg png gif webp svg ico bmp tif tiff css js mjs json xml rss atom zip gz tgz rar 7z tar mp3 wav "
               "ogg mp4 m4v avi mov webm mkv woff woff2 ttf otf eot exe msi dmg apk ipa iso doc ppt pptx xls xlsx "
               "docx csv".split())
TRACKING = re.compile(r"^(utm_.*|fbclid|gclid|msclkid|mc_cid|mc_eid|_ga|_gl|ref|source)$", re.I)


class UnsafeURL(Exception):
    """An address the crawler must not visit."""


class CrawlError(Exception):
    pass


# ------------------------------------------------------------------ addresses
def _resolve(host: str) -> list[str]:
    return list({i[4][0] for i in socket.getaddrinfo(host, None)})


def check_url(url: str):
    """Raise UnsafeURL unless the address is http(s) on a host that resolves only to public addresses."""
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise UnsafeURL(_("Only http and https addresses can be crawled."))
    if p.username or p.password:
        raise UnsafeURL(_("Addresses with a user name or password are not allowed."))
    host = p.hostname.lower().rstrip(".")
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal", ".lan", ".home", ".corp")):
        raise UnsafeURL(_("{0} is an internal address, which the crawler never visits.").format(host))
    try:
        ips = _resolve(host)
    except (OSError, UnicodeError):
        raise UnsafeURL(_("{0} could not be found.").format(host))
    if not ips:
        raise UnsafeURL(_("{0} could not be found.").format(host))
    for ip in ips:
        try:
            a = ipaddress.ip_address(ip.split("%", 1)[0])
        except ValueError:
            raise UnsafeURL(_("{0} has an address the crawler does not understand.").format(host))
        if getattr(a, "ipv4_mapped", None):
            a = a.ipv4_mapped
        if not a.is_global or a.is_multicast:
            raise UnsafeURL(_("{0} points to a private or internal network address, which the crawler never visits.")
                            .format(host))
    return p


def normalise(url: str) -> str | None:
    """Canonical form used for de-duplication: no fragment, no tracking parameters, lower-case host."""
    url, _frag = urldefrag((url or "").strip())
    try:
        p = urlparse(url)
        port = p.port
    except ValueError:
        return None
    if p.scheme not in ("http", "https") or not p.hostname:
        return None
    query = urlencode(sorted((k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if not TRACKING.match(k)))
    path = re.sub(r"/{2,}", "/", p.path or "/")
    netloc = p.hostname.lower() + (f":{port}" if port and port not in (80, 443) else "")
    return urlunparse((p.scheme, netloc, path, "", query, ""))


def _bare(host: str) -> str:
    host = (host or "").lower()
    return host[4:] if host.startswith("www.") else host


def same_site(a: str, b: str) -> bool:
    return _bare(urlparse(a).hostname or "") == _bare(urlparse(b).hostname or "")


# ------------------------------------------------------------------ fetching
def _raw_get(session, url: str, limit: int):
    """One request, no redirects. Returns (status, headers with lower-case keys, body up to `limit` bytes)."""
    r = session.get(url, timeout=20, allow_redirects=False, stream=True)
    try:
        body = b""
        for chunk in r.iter_content(65536):
            body += chunk
            if len(body) > limit:
                raise CrawlError(_("larger than {0} MB").format(limit // (1024 * 1024)))
        return r.status_code, {k.lower(): v for k, v in r.headers.items()}, body
    finally:
        r.close()


class Fetcher:
    def __init__(self, delay: float = 1.0):
        self.s = requests.Session()
        self.s.headers["User-Agent"] = UA.format(site=frappe.utils.get_url())
        self.s.headers["Accept"] = "text/html,application/xhtml+xml,application/pdf;q=0.8,text/plain;q=0.5"
        self.delay = max(MIN_DELAY, flt(delay))
        self._last = 0.0

    def get(self, url: str, limit: int = MAX_HTML):
        """GET with redirects followed by hand, each hop checked again. Returns (final_url, status, headers, body)."""
        for _hop in range(6):
            check_url(url)
            wait = self._last + self.delay - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            status, headers, body = _raw_get(self.s, url, limit)
            if status in (301, 302, 303, 307, 308) and headers.get("location"):
                nxt = normalise(urljoin(url, headers["location"]))
                if not nxt:
                    raise CrawlError(_("bad redirect"))
                url = nxt
                continue
            return url, status, headers, body
        raise CrawlError(_("too many redirects"))


def robots(fetcher: Fetcher, root: str):
    rp = robotparser.RobotFileParser()
    try:
        _u, status, _h, body = fetcher.get(root + "/robots.txt", 512 * 1024)
    except (UnsafeURL, CrawlError, requests.RequestException):
        status, body = 404, b""
    if status in (401, 403):
        rp.disallow_all = True
        rp.modified()
        return rp, []
    lines = body.decode("utf-8", "replace").splitlines() if status == 200 else []
    rp.parse(lines)
    return rp, [ln.split(":", 1)[1].strip() for ln in lines if ln.lower().startswith("sitemap:")]


def sitemap_urls(fetcher: Fetcher, start: list[str], limit: int) -> list[str]:
    out, queue, seen = [], list(start), set()
    while queue and len(out) < limit and len(seen) < 25:
        sm = queue.pop(0)
        if sm in seen:
            continue
        seen.add(sm)
        try:
            _u, status, _h, body = fetcher.get(sm, 10 * 1024 * 1024)
        except (UnsafeURL, CrawlError, requests.RequestException):
            continue
        if status != 200:
            continue
        if body[:2] == b"\x1f\x8b":
            try:
                body = zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(body, 50 * 1024 * 1024)
            except zlib.error:
                continue
        index = b"<sitemapindex" in body[:4096]
        for loc in re.findall(rb"<loc>\s*([^<\s]+)\s*</loc>", body):
            u = htmllib.unescape(loc.decode("utf-8", "replace"))
            (queue if index else out).append(u)
    return out[:limit]


def parse_page(url: str, body: bytes, headers: dict) -> dict:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(body, "html.parser")
    meta = soup.find("meta", attrs={"name": re.compile(r"^(robots|thinknxg-support-crawler)$", re.I)})
    directives = ((meta.get("content") if meta else "") or "").lower() + "," + headers.get("x-robots-tag", "").lower()
    nofollow = "nofollow" in directives or "none" in directives
    links = [] if nofollow else [
        urljoin(url, a["href"]) for a in soup.find_all("a", href=True)
        if "nofollow" not in " ".join(a.get("rel") or []).lower()]
    canonical = None
    link = soup.find("link", rel=lambda v: v and "canonical" in (v if isinstance(v, list) else [v]))
    if link and link.get("href"):
        canonical = normalise(urljoin(url, link["href"]))
    lang = ""
    if soup.html and soup.html.get("lang"):
        lang = soup.html["lang"].split("-")[0].lower()[:8]
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    main = soup.find("article") or soup.find("main") or soup.find(attrs={"role": "main"}) or soup.body or soup
    for bad in main.find_all(["nav", "header", "footer", "aside", "script", "style", "form", "noscript", "svg",
                              "iframe", "template", "button"]):
        bad.decompose()
    h1 = main.find("h1")
    if h1 and not title:
        title = h1.get_text(" ", strip=True)
    text = re.sub(r"\n\s*\n+", "\n\n", main.get_text("\n"))
    text = re.sub(r"[ \t ]+", " ", text).strip()
    return {"title": (title or url)[:140], "text": text, "links": links, "canonical": canonical, "language": lang,
            "noindex": "noindex" in directives or "none" in directives}


# ------------------------------------------------------------------ crawl
def queue(website: str):
    frappe.enqueue("thinknxg_support.integrations.ai.crawler.crawl", queue="long", timeout=4 * 3600,
                   website=website, job_id=f"thinknxg-crawl-{website}", deduplicate=True, enqueue_after_commit=True)


def _patterns(text: str | None) -> list[str]:
    return [x.strip() for x in (text or "").splitlines() if x.strip() and not x.strip().startswith("#")]


def _excluded(url: str, patterns: list[str]) -> bool:
    p = urlparse(url)
    path = p.path + (f"?{p.query}" if p.query else "")
    for pat in patterns:
        if fnmatch.fnmatch(path, pat) or fnmatch.fnmatch(url, pat) or (not any(c in pat for c in "*?[") and pat in url):
            return True
    return False


def crawl(website: str) -> str:
    """Background job. Returns (and stores) a one-line result."""
    from thinknxg_support.integrations.ai import documents, retrieval

    lock = frappe.cache.make_key(f"thinknxg_support:crawl:{website}")
    if not frappe.cache.set(lock, 1, nx=True, ex=4 * 3600):
        return _("A crawl of this site is already running.")
    site = frappe.get_doc(SITE, website)
    stats = {"new": 0, "changed": 0, "same": 0, "gone": 0, "skipped": 0, "errors": 0}
    errors: list[str] = []
    try:
        site.db_set("last_crawl_status", _("Crawling…"), update_modified=False)
        frappe.db.commit()
        start = normalise(site.start_url)
        check_url(start)
        fetcher = Fetcher(site.delay_seconds if site.delay_seconds is not None else 1)
        p = urlparse(start)
        rp, sitemaps = robots(fetcher, f"{p.scheme}://{p.netloc}")
        include, exclude = _patterns(site.include_paths), _patterns(site.exclude_patterns)
        max_pages = min(max(cint(site.max_pages) or 200, 1), MAX_PAGES)
        max_depth = min(max(cint(site.max_depth), 0), 10)

        def allowed(u: str) -> bool:
            q = urlparse(u)
            ext = q.path.rsplit(".", 1)[-1].lower() if "." in q.path.rsplit("/", 1)[-1] else ""
            if not same_site(u, start) or ext in SKIP_EXT or (ext == "pdf" and not site.include_pdfs):
                return False
            if include and not any(q.path.startswith(i) for i in include) and u != start:
                return False
            return not _excluded(u, exclude) and rp.can_fetch(AGENT, u)

        todo = deque([(start, 0)])
        if site.use_sitemap:
            for u in sitemap_urls(fetcher, sitemaps or [f"{p.scheme}://{p.netloc}/sitemap.xml"], max_pages * 2):
                nu = normalise(u)
                if nu:
                    todo.append((nu, 1))
        existing = {r.url: r for r in frappe.get_all(PAGE, filters={"website": site.name},
                                                     fields=["name", "url", "status", "content_hash"])}
        seen, stored, fetched, start_ok = set(), set(), 0, False
        while todo and fetched < max_pages:
            url, depth = todo.popleft()
            if url in seen:
                continue
            seen.add(url)
            if not allowed(url):
                stats["skipped"] += 1
                continue
            is_pdf = url.lower().endswith(".pdf")
            try:
                final, status, headers, body = fetcher.get(url, MAX_PDF if is_pdf else MAX_HTML)
            except UnsafeURL:
                stats["skipped"] += 1
                continue
            except (CrawlError, requests.RequestException) as e:
                stats["errors"] += 1
                errors.append(f"{url}: {str(e)[:80]}")
                continue
            final = normalise(final) or url
            if final != url:
                if final in seen or not allowed(final):
                    stats["skipped"] += 1
                    continue
                seen.add(final)
            fetched += 1
            if status != 200:
                if status not in (404, 410):
                    stats["errors"] += 1
                    errors.append(f"{final}: HTTP {status}")
                continue
            if url == start:
                start_ok = True
            ctype = (headers.get("content-type") or "").lower()
            lang = site.language or ""
            try:
                if "pdf" in ctype or final.lower().endswith(".pdf"):
                    if not site.include_pdfs:
                        continue
                    text, _pages = documents.extract(body, "pdf")
                    title = re.sub(r"[-_]+", " ", final.rsplit("/", 1)[-1].rsplit(".", 1)[0]).strip() or final
                elif "html" in ctype or not ctype:
                    page = parse_page(final, body, headers)
                    if depth < max_depth:
                        for link in page["links"]:
                            nu = normalise(link)
                            if nu and nu not in seen:
                                todo.append((nu, depth + 1))
                    if page["canonical"] and page["canonical"] != final and same_site(page["canonical"], start):
                        if page["canonical"] not in seen:
                            todo.appendleft((page["canonical"], depth))
                        stats["skipped"] += 1
                        continue
                    if page["noindex"]:
                        stats["skipped"] += 1
                        continue
                    text, title, lang = page["text"], page["title"], lang or page["language"]
                else:
                    stats["skipped"] += 1
                    continue
            except documents.ExtractError as e:
                stats["errors"] += 1
                errors.append(f"{final}: {e}")
                continue
            if len(text) < MIN_TEXT:
                stats["skipped"] += 1
                continue
            _store(site, final, title, text, depth, lang, existing, stats)
            stored.add(final)
            if fetched % 20 == 0:
                frappe.db.commit()
        complete = not todo and start_ok
        if complete:
            for url, row in existing.items():
                if url not in stored and row.status == "Active":
                    frappe.db.set_value(PAGE, row.name, "status", "Gone", update_modified=False)
                    frappe.db.delete(CHUNK, {"source_doctype": PAGE, "source_name": row.name})
                    stats["gone"] += 1
        result = _("{0} pages read: {1} new, {2} changed, {3} unchanged, {4} removed, {5} skipped, {6} errors.").format(
            fetched, stats["new"], stats["changed"], stats["same"], stats["gone"], stats["skipped"], stats["errors"])
        if not complete:
            result += " " + (_("Stopped at the page limit; pages not reached are kept.") if todo else
                             _("The start page could not be read; nothing was removed."))
        if errors:
            result += " " + "; ".join(errors[:3])
    except UnsafeURL as e:
        result = str(e)
    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(title="thinkNXG Support: website crawl failed")
        result = _("Crawl failed: {0}").format(str(e)[:200])
    finally:
        frappe.cache.delete(lock)
    site.db_set({"last_crawl_on": now_datetime(), "last_crawl_status": result[:1000],
                 "page_count": frappe.db.count(PAGE, {"website": site.name, "status": "Active"})},
                update_modified=False)
    frappe.db.set_single_value("Support AI Settings", "chunk_count", frappe.db.count(CHUNK))
    retrieval.bump_version()
    frappe.db.commit()
    return result


def _store(site, url, title, text, depth, lang, existing, stats):
    from thinknxg_support.integrations.ai import retrieval

    text = text[:200_000]
    h = hashlib.sha256(f"{title}\n{text}".encode()).hexdigest()
    row = existing.get(url)
    now = now_datetime()
    if row and (row.status == "Excluded" or (row.status == "Active" and row.content_hash == h)):
        frappe.db.set_value(PAGE, row.name, "last_fetched", now, update_modified=False)
        stats["same"] += 1
        return
    values = {"title": title, "text": text, "content_hash": h, "status": "Active", "depth": depth,
              "language": lang or None, "last_fetched": now}
    if row:
        doc = frappe.get_doc(PAGE, row.name)
        doc.update(values)
        stats["changed"] += 1
    else:
        doc = frappe.get_doc({"doctype": PAGE, "website": site.name, "url": url, **values})
        stats["new"] += 1
    doc.flags.from_crawler = True
    doc.flags.ignore_permissions = True
    doc.save() if row else doc.insert()
    try:
        retrieval.index_source(PAGE, doc.name)
    except Exception:
        frappe.log_error(title="thinkNXG Support: crawled page could not be indexed")


def reindex(website: str):
    from thinknxg_support.integrations.ai import retrieval

    for name in frappe.get_all(PAGE, filters={"website": website}, pluck="name"):
        retrieval.index_source(PAGE, name)
    frappe.db.commit()


def remove_pages(website: str):
    from thinknxg_support.integrations.ai import retrieval

    names = frappe.get_all(PAGE, filters={"website": website}, pluck="name")
    if names:
        frappe.db.delete(CHUNK, {"source_doctype": PAGE, "source_name": ["in", names]})
        frappe.db.delete(PAGE, {"website": website})
    retrieval.bump_version()


def scheduled():
    """Daily: crawl the sites whose refresh is due."""
    for s in frappe.get_all(SITE, filters={"enabled": 1, "refresh": ["in", ["Daily", "Weekly"]]},
                            fields=["name", "refresh", "last_crawl_on"]):
        days = 1 if s.refresh == "Daily" else 7
        if not s.last_crawl_on or get_datetime(s.last_crawl_on) <= add_to_date(now_datetime(), hours=-(days * 24 - 1)):
            queue(s.name)
