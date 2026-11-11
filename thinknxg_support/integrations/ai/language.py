"""1.11: multilingual answers.

detect() recognises a language from its script (Arabic, Hindi, Chinese, ...) or, for Latin-script languages, from
common words; it returns None when unsure rather than guessing. search() also looks the question up in the
knowledge base's own language (one short, cached AI call) when the customer writes in another language and the
index has no multilingual embeddings. localize() translates fixed messages (no answer, handoff) for the customer,
cached for 30 days. Everything falls back to the original behaviour when the AI is off or over budget.
"""
from __future__ import annotations

import hashlib
import re

import frappe
from frappe.utils import cint, strip_html

NAMES = {"en": "English", "ar": "Arabic", "hi": "Hindi", "ur": "Urdu", "fa": "Persian", "fr": "French",
         "es": "Spanish", "de": "German", "pt": "Portuguese", "it": "Italian", "nl": "Dutch", "tr": "Turkish",
         "id": "Indonesian", "ms": "Malay", "tl": "Filipino", "ml": "Malayalam", "ta": "Tamil", "te": "Telugu",
         "bn": "Bengali", "ru": "Russian", "zh": "Chinese", "ja": "Japanese", "ko": "Korean", "th": "Thai",
         "he": "Hebrew", "el": "Greek", "sw": "Swahili"}
SCRIPTS = [("arabic", re.compile(r"[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]")),
           ("kana", re.compile(r"[぀-ヿ]")), ("ko", re.compile(r"[가-힯ᄀ-ᇿ]")),
           ("zh", re.compile(r"[一-鿿]")), ("hi", re.compile(r"[ऀ-ॿ]")),
           ("bn", re.compile(r"[ঀ-৿]")), ("ta", re.compile(r"[஀-௿]")),
           ("te", re.compile(r"[ఀ-౿]")), ("ml", re.compile(r"[ഀ-ൿ]")),
           ("th", re.compile(r"[฀-๿]")), ("he", re.compile(r"[֐-׿]")),
           ("el", re.compile(r"[Ͱ-Ͽ]")), ("ru", re.compile(r"[Ѐ-ӿ]")),
           ("latin", re.compile(r"[A-Za-zÀ-ɏ]"))]
URDU = re.compile(r"[ٹڈڑںھہےۓ]")
PERSIAN = re.compile(r"[پچژگکی]")
ARABIC_ONLY = re.compile(r"[ةكيى]")
LATIN = {
    "en": "the and is are you your to of in for it this that what how can my with have not please do does order "
          "help hi hello thanks thank need want when where why get",
    "fr": "le la les et est vous votre de des du pour un une je mon ma pas que qui avec sur bonjour merci comment "
          "commande aide besoin",
    "es": "el la los las y es usted su del para un una yo mi no que con por hola gracias cómo está pedido ayuda "
          "necesito",
    "de": "der die das und ist sie ihr zu von für ein eine ich mein nicht mit auf hallo danke wie bitte bestellung "
          "hilfe",
    "pt": "o os as e é você seu do da para um uma eu meu não que com por olá obrigado como pedido ajuda preciso",
    "it": "il lo gli le è lei suo di del per un una io mio non che con ciao grazie come ordine aiuto",
    "nl": "het en is u uw van voor een ik mijn niet met op hallo bedankt hoe bestelling hulp",
    "tr": "ve bir bu için ne nasıl ben benim değil ile merhaba teşekkürler sipariş mı mi var yok yardım",
    "id": "dan yang di ke dari untuk saya tidak dengan apa bagaimana terima kasih pesanan ini itu ada bantuan",
}
LATIN_SETS = {k: set(v.split()) for k, v in LATIN.items()}
WORDS = re.compile(r"[^\W\d_]+", re.UNICODE)
MSG = "Support Portal Message"


def name(code: str | None) -> str:
    return NAMES.get((code or "").lower(), code or "")


def detect(text: str | None) -> str | None:
    text = strip_html(text or "")
    counts = {key: len(rx.findall(text)) for key, rx in SCRIPTS}
    letters = sum(counts.values())
    if letters < 3:
        return None
    if counts["kana"]:
        return "ja"
    key, n = max(counts.items(), key=lambda kv: kv[1])
    if n / letters < 0.5:
        return None
    if key == "arabic":
        urdu, persian, arabic = len(URDU.findall(text)), len(PERSIAN.findall(text)), len(ARABIC_ONLY.findall(text))
        if urdu and urdu >= arabic:
            return "ur"
        if persian > arabic:
            return "fa"
        return "ar"
    if key != "latin":
        return key
    words = [w.casefold() for w in WORDS.findall(text)]
    scores = sorted(((sum(1 for w in words if w in s), k) for k, s in LATIN_SETS.items()), reverse=True)
    best, second = scores[0], scores[1]
    if best[0] >= 2 and best[0] > second[0] or (best[0] == 1 and second[0] == 0 and len(words) <= 4):
        return best[1]
    return None


def cfg():
    return frappe.get_cached_doc("Support AI Settings")


def knowledge_language(c=None) -> str:
    return ((c or cfg()).get("knowledge_language") or "en").strip().lower()[:8] or "en"


def conversation_language(conv) -> str | None:
    """The customer's language: the 1.10 message analysis when it ran, else detected from their latest messages."""
    if conv is None:
        return None
    if conv.get("customer_language"):
        return str(conv.customer_language).lower()[:8]
    rows = frappe.get_all(MSG, filters={"conversation": conv.name, "direction": "Inbound"}, order_by="creation desc",
                          limit=5, pluck="content")
    return detect(" ".join(strip_html(r or "") for r in rows)) if rows else None


def language_rule(c, lang: str | None) -> str:
    if c.get("answer_language") == "Knowledge language":
        return f"Reply in {name(knowledge_language(c))}."
    if lang:
        n = name(lang)
        return f"The customer writes in {n}: reply in {n}, even when the passages are in another language."
    return "Reply in the language the customer wrote in, even when the passages are in another language."


def _ai_ready(c) -> bool:
    from thinknxg_support.integrations.ai import providers

    return bool(c.get("model")) and providers.budget_left()


def _translate(text: str, target: str, kind_hint: str, conversation: str | None, max_tokens: int,
               cached_only: bool = False) -> str | None:
    from thinknxg_support.integrations.ai import common

    key = frappe.cache.make_key(f"thinknxg_support:l10n:{target}:{hashlib.sha1(text.encode()).hexdigest()}")
    hit = frappe.cache.get(key)
    if hit:
        return hit.decode() if isinstance(hit, bytes) else str(hit)
    if cached_only or frappe.flags.get("thinknxg_no_ai"):
        return None
    try:
        out = common.call("Translation", f"Translate {kind_hint} into {name(target)}. Keep names, numbers, codes and "
                                         "links unchanged. Reply with only the translation.",
                          text[:2000], conversation=conversation, max_tokens=max_tokens, temperature=0)
    except Exception:
        return None
    out = (out or "").strip()
    if out:
        frappe.cache.set(key, out, ex=30 * 86400)
    return out or None


def search(question: str, audience: str, conv=None, k: int | None = None, translate: bool = True) -> dict:
    """Knowledge search that also works across languages. Returns {passages, language, translated}.

    translate=False: never spend an AI call on translating the question (1.16, "No AI Calls When Nothing Is Found");
    a translation made earlier is still used."""
    from thinknxg_support.integrations.ai import retrieval

    c = cfg()
    lang = detect(question) or conversation_language(conv)
    passages = retrieval.search(question, audience, k=k)
    out = {"passages": passages, "language": lang, "translated": None}
    kb = knowledge_language(c)
    semantic = bool(c.get("use_embeddings") and c.get("embedding_model"))
    if not lang or lang == kb or semantic or not cint(c.get("translate_questions")) or not _ai_ready(c):
        return out
    translated = _translate(question, kb, "this customer support question (for a knowledge-base search)",
                            conv.name if conv else None, 200, cached_only=not translate)
    if not translated or translated.strip().casefold() == question.strip().casefold():
        return out
    best = {}
    for p in passages + retrieval.search(translated, audience, k=k):
        key = (p["doctype"], p["name"], p["content"])
        if key not in best or p["score"] > best[key]["score"]:
            best[key] = p
    limit = int(k or c.top_k or 4)
    merged = sorted(best.values(), key=lambda p: p["score"], reverse=True)[:limit]
    out["passages"] = [{**p, "id": f"S{i}"} for i, p in enumerate(merged, 1)]
    out["translated"] = translated
    return out


def localize(conv, text: str | None) -> str | None:
    """A fixed message (no answer, handoff, offline) in the customer's language when it differs from the KB's."""
    if not text:
        return text
    try:
        c = cfg()
        if not cint(c.get("localize_messages")):
            return text
        lang = conversation_language(conv)
        if not lang or lang == knowledge_language(c) or detect(text) == lang or not _ai_ready(c):
            return text
        return _translate(text, lang, "this customer service message", conv.name, 300) or text
    except Exception:
        frappe.log_error(title="thinkNXG Support: message translation failed")
        return text
