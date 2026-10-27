"""Provider-agnostic LLM adapter with streaming.

Two wire formats cover most providers:
* "OpenAI Compatible": POST {base}/chat/completions and {base}/embeddings
* "Anthropic":        POST {base}/v1/messages
Nothing here stores prompts or answers; only token counts and timings are returned.
"""
from __future__ import annotations

import json
import time

import frappe
import requests
from frappe import _


class AIError(Exception):
    def __init__(self, message, kind="Error"):
        super().__init__(message)
        self.kind = kind  # Error | Timeout


def cfg():
    return frappe.get_cached_doc("Support AI Settings")


def _key(field="api_key"):
    try:
        return frappe.get_single("Support AI Settings").get_password(field, raise_exception=False) or ""
    except Exception:
        return ""


def _post_stream(url, headers, payload, timeout):
    try:
        r = requests.post(url, headers=headers, json=payload, stream=True, timeout=(10, timeout))
    except requests.Timeout:
        raise AIError(_("The AI provider did not respond in time."), "Timeout")
    except requests.RequestException as e:
        raise AIError(f"network: {e.__class__.__name__}")
    if r.status_code >= 400:
        try:
            body = r.json()
            detail = (body.get("error") or {}).get("message") if isinstance(body.get("error"), dict) else body.get("error")
        except ValueError:
            detail = r.text[:300]
        raise AIError(f"HTTP {r.status_code}: {str(detail or '')[:300]}")
    return r


def _sse(resp, deadline):
    for raw in resp.iter_lines(decode_unicode=True):
        if time.monotonic() > deadline:
            resp.close()
            raise AIError(_("The AI provider did not finish in time."), "Timeout")
        if not raw or not raw.startswith("data:"):
            continue
        data = raw[5:].strip()
        if data == "[DONE]":
            return
        try:
            yield json.loads(data)
        except ValueError:
            continue


def complete(system: str, messages: list[dict], on_delta=None, max_tokens=None, temperature=None) -> dict:
    """Stream a completion. Returns {text, prompt_tokens, completion_tokens, latency_ms, first_token_ms, model}."""
    s = cfg()
    timeout = int(s.timeout_seconds or 30)
    start = time.monotonic()
    deadline = start + timeout
    max_tokens = int(max_tokens or s.max_output_tokens or 600)
    temperature = float(s.temperature if temperature is None else temperature)
    text, first, usage = [], None, {"prompt_tokens": 0, "completion_tokens": 0}

    def emit(piece):
        nonlocal first
        if not piece:
            return
        if first is None:
            first = time.monotonic()
        text.append(piece)
        if on_delta:
            on_delta("".join(text))

    base = (s.api_base_url or "").rstrip("/")
    if s.provider == "Anthropic":
        url = base + ("/messages" if base.endswith("/v1") else "/v1/messages")
        headers = {"x-api-key": _key(), "anthropic-version": "2023-06-01", "content-type": "application/json"}
        payload = {"model": s.model, "system": system, "messages": messages, "max_tokens": max_tokens,
                   "temperature": temperature, "stream": True}
        resp = _post_stream(url, headers, payload, timeout)
        for ev in _sse(resp, deadline):
            t = ev.get("type")
            if t == "content_block_delta":
                emit((ev.get("delta") or {}).get("text"))
            elif t == "message_start":
                u = (ev.get("message") or {}).get("usage") or {}
                usage["prompt_tokens"] = u.get("input_tokens") or 0
            elif t == "message_delta":
                usage["completion_tokens"] = ((ev.get("usage") or {}).get("output_tokens")) or usage["completion_tokens"]
            elif t == "error":
                raise AIError(str((ev.get("error") or {}).get("message") or "provider error")[:300])
    else:
        url = base + "/chat/completions"
        headers = {"Content-Type": "application/json"}
        if _key():
            headers["Authorization"] = f"Bearer {_key()}"
        payload = {"model": s.model, "messages": [{"role": "system", "content": system}] + messages,
                   "max_tokens": max_tokens, "temperature": temperature, "stream": True,
                   "stream_options": {"include_usage": True}}
        try:
            resp = _post_stream(url, headers, payload, timeout)
        except AIError as e:
            if "HTTP 400" not in str(e):
                raise
            payload.pop("stream_options")  # some compatible servers reject it
            resp = _post_stream(url, headers, payload, timeout)
        for ev in _sse(resp, deadline):
            for ch in ev.get("choices") or []:
                emit((ch.get("delta") or {}).get("content"))
            if ev.get("usage"):
                usage["prompt_tokens"] = ev["usage"].get("prompt_tokens") or 0
                usage["completion_tokens"] = ev["usage"].get("completion_tokens") or 0
    end = time.monotonic()
    return {"text": "".join(text), "model": s.model, "provider": s.provider,
            "latency_ms": int((end - start) * 1000),
            "first_token_ms": int(((first or end) - start) * 1000), **usage}


def embed(texts: list[str]) -> list[list[float]]:
    s = cfg()
    if not (s.use_embeddings and s.embedding_model):
        raise AIError(_("Embeddings are not configured."))
    url = (s.embedding_base_url or s.api_base_url or "").rstrip("/") + "/embeddings"
    key = _key("embedding_api_key") or _key()
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    out = []
    for i in range(0, len(texts), 64):
        batch = texts[i:i + 64]
        try:
            r = requests.post(url, headers=headers, json={"model": s.embedding_model, "input": batch},
                              timeout=(10, int(s.timeout_seconds or 30) * 2))
        except requests.RequestException as e:
            raise AIError(f"network: {e.__class__.__name__}")
        if r.status_code >= 400:
            raise AIError(f"HTTP {r.status_code}: {r.text[:300]}")
        data = sorted(r.json().get("data") or [], key=lambda d: d.get("index", 0))
        if len(data) != len(batch):
            raise AIError(_("The embedding service returned an unexpected number of vectors."))
        out.extend(d["embedding"] for d in data)
    return out


def test() -> str:
    s = cfg()
    if not s.model:
        frappe.throw(_("Enter the model name first."))
    try:
        r = complete("You are a connection test. Reply with the single word OK.",
                     [{"role": "user", "content": "Connection test"}], max_tokens=10, temperature=0)
    except AIError as e:
        log_usage(kind="Test", status=e.kind, error=str(e))
        frappe.throw(_("The model call failed: {0}").format(e))
    log_usage(kind="Test", status="Success", result=r)
    msg = _("Connected to {0}. Reply: {1}. First token in {2} ms.").format(
        s.model, (r["text"] or "").strip()[:40], r["first_token_ms"])
    if s.use_embeddings:
        try:
            v = embed(["connection test"])
            msg += " " + _("Embeddings OK ({0} dimensions).").format(len(v[0]))
        except AIError as e:
            msg += " " + _("Embeddings failed: {0}").format(e)
    return msg


def log_usage(kind="Answer", status="Success", result=None, conversation=None, error=None, confidence=None,
              passages=0, top_relevance=0.0) -> str | None:
    try:
        s = cfg()
        result = result or {}
        doc = frappe.get_doc({
            "doctype": "Support AI Usage Log", "conversation": conversation, "kind": kind, "status": status,
            "provider": result.get("provider") or s.provider, "model": result.get("model") or s.model,
            "prompt_tokens": result.get("prompt_tokens") or 0, "completion_tokens": result.get("completion_tokens") or 0,
            "total_tokens": (result.get("prompt_tokens") or 0) + (result.get("completion_tokens") or 0),
            "latency_ms": result.get("latency_ms") or 0, "first_token_ms": result.get("first_token_ms") or 0,
            "confidence": confidence, "passages": passages, "top_relevance": top_relevance,
            "error": (error or "")[:500] or None,
        })
        doc.insert(ignore_permissions=True)
        frappe.cache.delete_value("thinknxg_support:ai_tokens_today")
        return doc.name
    except Exception:
        frappe.logger("thinknxg_support").exception("could not write AI usage log")
        return None


def tokens_used_today() -> int:
    key = "thinknxg_support:ai_tokens_today"
    val = frappe.cache.get_value(key)
    if val is None:
        val = frappe.db.sql("select coalesce(sum(total_tokens),0) from `tabSupport AI Usage Log` where creation >= %s",
                            (frappe.utils.nowdate(),))[0][0]
        frappe.cache.set_value(key, int(val), expires_in_sec=60)
    return int(val)


def budget_left() -> bool:
    budget = int(cfg().daily_token_budget or 0)
    return budget <= 0 or tokens_used_today() < budget
