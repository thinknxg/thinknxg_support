"""Rebrand help-article HTML safely.

Only human-readable text changes: text nodes plus alt/title/aria-label attributes. Code (code, pre, kbd,
samp), scripts, styles, URLs, e-mail addresses, file paths and dotted API names such as frappe.get_doc
are never touched. Longer phrases are replaced first so "Frappe Framework" wins over "Frappe".
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup, Comment, NavigableString

SKIP_TAGS = {"code", "pre", "kbd", "samp", "script", "style", "var", "tt"}
TEXT_ATTRS = ("alt", "title", "aria-label")
DEFAULT_RULES = [
    ("Frappe Framework", "thinkNXG Framework"),
    ("Frappe Cloud", "thinkNXG Cloud"),
    ("Frappe HR", "thinkNXG HR"),
    ("ERPNext", "thinkNXG ERP"),
    ("Frappe", "thinkNXG"),
]

# Things a reviewer should look at: the rebrand cannot make them right on its own.
FLAGS = [
    (re.compile(r"frappe\.cloud|frappecloud\.com|frappe\.io|erpnext\.com|frappehr\.com", re.I),
     "Links or mentions of Frappe's own websites"),
    (re.compile(r"\bFrappe Technologies\b|\bFrappe (?:team|support|partner)s?\b", re.I),
     "Mentions Frappe as a company, team or support provider"),
    (re.compile(r"[\w.+-]+@(?:frappe|erpnext)\.[\w.]+", re.I), "Frappe e-mail addresses"),
    (re.compile(r"(?:\$|₹|USD|INR|EUR)\s?\d|\b(?:pricing|price plan|per month|/month|subscription plan)\b", re.I),
     "Prices or plans that may not apply to thinkNXG"),
    (re.compile(r"\bFrappe Cloud\b", re.I),
     "Describes Frappe Cloud hosting: steps, dashboards or billing may differ on thinkNXG Cloud"),
    (re.compile(r"\b(?:marketplace|partner portal|support\.frappe\.io)\b", re.I), "Frappe marketplace or partner programme"),
]


def compile_rules(rules):
    """rules: iterable of (find, replace, match_case). Returns compiled patterns, longest first."""
    out = []
    for find, repl, match_case in sorted(rules, key=lambda r: len(r[0] or ""), reverse=True):
        find = (find or "").strip()
        if not find:
            continue
        # not part of a word, a URL, a domain, an e-mail, a path or a dotted/underscored identifier
        pat = rf"(?<![\w.@_\\]){re.escape(find)}(?![\w@_\\]|\.[A-Za-z_])"
        out.append((re.compile(pat, 0 if match_case else re.IGNORECASE), repl))
    return out


def _apply(text: str, compiled) -> tuple[str, int]:
    total = 0
    for rx, repl in compiled:
        text, n = rx.subn(repl, text)
        total += n
    return text, total


def _protected(node) -> bool:
    for parent in node.parents:
        if getattr(parent, "name", None) in SKIP_TAGS:
            return True
    return False


URLISH = re.compile(r"(https?://\S+|www\.\S+|[\w.+-]+@[\w-]+\.[\w.-]+|(?<![\w])\.{0,2}/[\w.-]+(?:/[\w.-]+)*"
                    r"|\b[\w-]+\.(?:io|com|cloud|org|net|in)\b(?:/\S*)?)")


def rebrand_text(text: str, compiled) -> tuple[str, int]:
    """Rebrand a plain string, leaving URLs, e-mails and paths inside it untouched."""
    parts, total = [], 0
    last = 0
    for m in URLISH.finditer(text or ""):
        chunk, n = _apply(text[last:m.start()], compiled)
        parts.append(chunk)
        parts.append(m.group(0))
        total += n
        last = m.end()
    chunk, n = _apply((text or "")[last:], compiled)
    parts.append(chunk)
    return "".join(parts), total + n


def rebrand_html(html: str, compiled) -> tuple[str, int]:
    soup = BeautifulSoup(html or "", "html.parser")
    total = 0
    for node in list(soup.find_all(string=True)):
        if isinstance(node, Comment) or _protected(node):
            continue
        new, n = rebrand_text(str(node), compiled)
        if n:
            node.replace_with(NavigableString(new))
            total += n
    for tag in soup.find_all(True):
        if tag.name in SKIP_TAGS:
            continue
        for attr in TEXT_ATTRS:
            if tag.has_attr(attr) and isinstance(tag[attr], str):
                new, n = rebrand_text(tag[attr], compiled)
                if n:
                    tag[attr] = new
                    total += n
    return str(soup), total


# ------------------------------------------------------------------ websites and e-mail addresses
DEFAULT_LINK_RULES = [
    # kind, Frappe address, thinkNXG address (blank = fill in, row stays off), keep path, enabled
    ("Website", "docs.frappe.io/erpnext", "https://docs.thinknxg.com/thinknxgerp", 1, 1),
    ("Website", "docs.frappe.io/framework", "", 1, 0),
    ("Website", "docs.frappe.io/hr", "", 1, 0),
    ("Website", "docs.frappe.io/cloud", "", 1, 0),
    ("Website", "docs.frappe.io", "", 1, 0),
    ("Website", "frappe.io", "", 0, 0),
    ("Website", "frappe.cloud", "", 0, 0),
    ("Website", "erpnext.com", "", 0, 0),
    ("Website", "frappehr.com", "", 0, 0),
    ("Website", "discuss.frappe.io", "", 0, 0),
    ("Website", "school.frappe.io", "", 0, 0),
    ("E-mail", "frappe.io", "", 0, 0),
    ("E-mail", "erpnext.com", "", 0, 0),
]

ATTRIBUTION_CLASS = "tx-attribution"
URL_TOKEN = re.compile(r"(?<![\w@./-])(?:(?:https?://|mailto:)?[\w.+-]+@(?:[\w-]+\.)+[a-z]{2,}"
                       r"|(?:https?://)?(?:www\.)?(?:[\w-]+\.)+[a-z]{2,}(?::\d+)?(?:/[^\s<>\"')\]]*)?)", re.I)
TRAILING = ".,;:!?"


def _split(addr: str) -> tuple[str, str]:
    addr = re.sub(r"^https?://", "", (addr or "").strip(), flags=re.I).lower()
    host, _s, path = addr.partition("/")
    return (host[4:] if host.startswith("www.") else host), ("/" + path.strip("/") if path.strip("/") else "")


def validate_link_rule(kind, find, replace_with, enabled) -> str | None:
    if not (find or "").strip():
        return "enter the Frappe address"
    if not enabled:
        return None
    if not (replace_with or "").strip():
        return "enter the thinkNXG address, or untick Enabled"
    if kind == "E-mail":
        if "/" in replace_with or "@" in replace_with or "." not in replace_with:
            return "for e-mail, enter only the new domain, e.g. thinknxg.com"
    elif not replace_with.strip().lower().startswith("https://"):
        return "the thinkNXG address must start with https://"
    return None


def compile_link_rules(rows):
    """rows: iterable of (kind, find, replace_with, keep_path). Longest Frappe address first."""
    out = []
    for kind, find, repl, keep in rows:
        if not (find and repl):
            continue
        host, path = _split(find)
        out.append({"kind": kind or "Website", "host": host, "path": path, "repl": repl.strip().rstrip("/"),
                    "keep": bool(keep), "len": len(host) + len(path)})
    return sorted(out, key=lambda r: r["len"], reverse=True)


def rewrite_address(addr: str, rules) -> str | None:
    """Return the thinkNXG version of one URL, bare domain or e-mail address, or None when no rule matches."""
    if not rules or not addr:
        return None
    m = re.match(r"^(mailto:)?([\w.+-]+)@([\w.-]+)(.*)$", addr, re.I)
    if m:
        domain = m.group(3).lower()
        for r in rules:
            if r["kind"] == "E-mail" and r["host"] == domain:
                return f"{m.group(1) or ''}{m.group(2)}@{r['repl']}{m.group(4)}"
        return None
    has_scheme = bool(re.match(r"^https?://", addr, re.I))
    rest = re.sub(r"^https?://", "", addr, flags=re.I)
    hostport, sep, tail = rest.partition("/")
    tail = sep + tail
    path_part = re.split(r"[?#]", tail, 1)[0]
    extra = tail[len(path_part):]
    host = hostport.lower().split(":")[0]
    host = host[4:] if host.startswith("www.") else host
    for r in rules:
        if r["kind"] != "Website" or r["host"] != host:
            continue
        p = path_part.rstrip("/")
        if r["path"] and not (p.lower() == r["path"] or p.lower().startswith(r["path"] + "/")):
            continue
        new = r["repl"] + (p[len(r["path"]):] + extra if r["keep"] else "")
        if not has_scheme:  # written as plain text, e.g. "docs.frappe.io/erpnext": keep it plain
            new = re.sub(r"^https?://", "", new, flags=re.I)
        return new
    return None


def _in_attribution(node) -> bool:
    for parent in [node, *node.parents]:
        cls = getattr(parent, "get", lambda *_a: None)("class") if hasattr(parent, "get") else None
        if cls and ATTRIBUTION_CLASS in cls:
            return True
    return False


def _rewrite_tokens(text: str, rules) -> tuple[str, int]:
    count = 0

    def repl(m):
        nonlocal count
        token = m.group(0)
        trail = ""
        while token and token[-1] in TRAILING:
            trail = token[-1] + trail
            token = token[:-1]
        new = rewrite_address(token, rules)
        if new is None:
            return m.group(0)
        count += 1
        return new + trail

    return URL_TOKEN.sub(repl, text or ""), count


def apply_link_rules(html: str, rules, skip_hosts=()) -> tuple[str, int]:
    """Move links, web addresses and e-mail addresses to thinkNXG. Code, image sources, the attribution
    footer and links to `skip_hosts` (the import source, handled when publishing) are left alone."""
    if not rules:
        return html, 0
    skip = {h.lower().removeprefix("www.") for h in skip_hosts if h}
    soup = BeautifulSoup(html or "", "html.parser")
    total = 0
    for a in soup.find_all("a", href=True):
        if _in_attribution(a):
            continue
        href = a["href"].strip()
        if _split(href)[0] in skip and not href.lower().startswith("mailto:"):
            continue
        new = rewrite_address(href, rules)
        if new:
            if not re.match(r"^(https?://|mailto:)", new, re.I) and not href.lower().startswith("mailto:"):
                new = "https://" + new
            a["href"] = new
            total += 1
    for node in list(soup.find_all(string=True)):
        if isinstance(node, Comment) or _protected(node) or _in_attribution(node.parent):
            continue
        new, n = _rewrite_tokens(str(node), rules)
        if n:
            node.replace_with(NavigableString(new))
            total += n
    return str(soup), total


WEBSITE_FLAG = "Links or mentions of Frappe's own websites"
EMAIL_FLAG = "Frappe e-mail addresses"


def review_flags(original_html: str, proposed_html: str | None = None) -> list[str]:
    """Website and e-mail notes look at the proposed text, so they clear once link rules cover them."""
    def views(h):
        return BeautifulSoup(h or "", "html.parser").get_text(" "), h or ""

    orig = views(original_html)
    prop = views(proposed_html) if proposed_html is not None else orig
    found = []
    for rx, why in FLAGS:
        text, raw = prop if why in (WEBSITE_FLAG, EMAIL_FLAG) else orig
        if rx.search(text) or rx.search(raw):
            found.append(why)
    return list(dict.fromkeys(found))
