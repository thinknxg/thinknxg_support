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


def review_flags(original_html: str) -> list[str]:
    text = BeautifulSoup(original_html or "", "html.parser").get_text(" ")
    raw = original_html or ""
    found = []
    for rx, why in FLAGS:
        if rx.search(text) or rx.search(raw):
            found.append(why)
    return list(dict.fromkeys(found))
