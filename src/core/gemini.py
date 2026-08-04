# ============================================================
#  gemini.py
#  Thin client for Google's Gemini API (free tier). Shared by the
#  fit ranker (bulk role scoring) and the cold-email generator, so
#  the whole project runs on one free LLM — no paid API.
#
#  Handles the three things every Gemini call in this repo needs:
#    - a model fallback chain: when one model's DAILY free-tier quota
#      is spent, roll to the next model's separate daily bucket
#    - RPM throttling: calls spaced a few seconds apart
#    - thinkingBudget 0: 2.5-family "thinking" otherwise silently eats
#      the output-token budget and truncates the reply
# ============================================================

from __future__ import annotations

import threading
import time

import requests

from src.core import config

# Free-tier quotas are PER MODEL and much smaller than advertised, so we
# keep a fallback chain: the configured model first, then flash as backup.
_MODELS = list(dict.fromkeys([config.GEMINI_MODEL, "gemini-flash-latest"]))
# Embedding model — free tier. Used by resume_kb for RAG retrieval. We request
# 768 dimensions (the model defaults to 3072) — plenty for a tiny résumé corpus
# and a third the storage.
_EMBED_MODEL = "gemini-embedding-001"
_EMBED_DIMS = 768
# Quotas are per (API key, model) — each free-trial key gets its own daily
# bucket per model. Tracks which combos are dead for the rest of this run.
_dead: set[tuple[str, str]] = set()
_lock = threading.Lock()
_next_ok = 0.0
_SPACING = 4.5                    # seconds between calls (RPM limit)


class GeminiUnavailable(RuntimeError):
    """No configured model can serve the request — either GEMINI_API_KEY is
    unset or every model's free-tier daily quota is exhausted. Callers should
    fall back (keyword fit score / template email) rather than crash."""


def _throttle() -> None:
    global _next_ok
    with _lock:
        wait = _next_ok - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _next_ok = time.monotonic() + _SPACING


def _quota_is_daily(resp) -> bool:
    try:
        for d in resp.json().get("error", {}).get("details", []):
            for v in d.get("violations", []):
                if "PerDay" in v.get("quotaId", ""):
                    return True
    except Exception:
        pass
    return False


def generate(prompt: str, *, system: str = "", max_output_tokens: int = 500,
             temperature: float = 0.1) -> str:
    """Return the text of a single Gemini completion.

    Rolls through every (API key, model) combo on daily-quota 429s and
    retries once on a per-minute 429, so several free-trial keys can be
    stacked in GEMINI_API_KEY (comma-separated) and it'll cycle to the next
    once one's quota is spent. Raises GeminiUnavailable when nothing can
    serve the request.
    """
    if not config.GEMINI_API_KEYS:
        raise GeminiUnavailable("GEMINI_API_KEY not set")

    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "maxOutputTokens": max_output_tokens,
            "temperature": temperature,
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}

    for key_i, key in enumerate(config.GEMINI_API_KEYS):
        for model in _MODELS:
            if (key, model) in _dead:
                continue
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
            for attempt in (1, 2):
                _throttle()
                r = requests.post(url, json=body, timeout=45,
                                  headers={"x-goog-api-key": key,
                                           "Content-Type": "application/json"})
                if r.status_code == 429:
                    if _quota_is_daily(r):
                        _dead.add((key, model))   # dead for the day — next model/key
                        print(f"  ⚠ gemini key #{key_i + 1}/{model}: daily quota exhausted, switching")
                        break
                    if attempt == 1:
                        time.sleep(25)  # per-minute window; back off and retry once
                        continue
                    break  # persistent RPM trouble — try the next model/key
                if r.status_code == 400 and "thinkingConfig" in body["generationConfig"]:
                    # Some newer model aliases reject thinkingBudget=0 outright.
                    # Drop it and retry once rather than losing the whole request.
                    body["generationConfig"].pop("thinkingConfig")
                    continue
                r.raise_for_status()
                return r.json()["candidates"][0]["content"]["parts"][0]["text"]
    raise GeminiUnavailable("gemini quota exhausted on all keys/models")


def embed(texts: str | list[str], *, task_type: str = "RETRIEVAL_DOCUMENT") -> list[list[float]]:
    """Return an embedding vector (list of floats) for each input text.

    Uses the free-tier text-embedding-004 model. `task_type` should be
    RETRIEVAL_DOCUMENT when embedding stored corpus chunks and RETRIEVAL_QUERY
    when embedding a search query — Gemini tunes the two ends of the retrieval
    asymmetrically, which improves match quality.

    A single string returns a 1-element list. Raises GeminiUnavailable when the
    key is unset or the embedding quota is spent, so callers can fall back to
    keyword-only retrieval rather than crash.
    """
    if not config.GEMINI_API_KEYS:
        raise GeminiUnavailable("GEMINI_API_KEY not set")
    if isinstance(texts, str):
        texts = [texts]
    if not texts:
        return []
    # gemini-embedding-001 serves one text per call (no synchronous batch), so
    # we loop. The corpus is embedded once (and only when a bullet changes), and
    # queries are single, so the call count stays tiny.
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{_EMBED_MODEL}:embedContent")
    out: list[list[float]] = []
    for t in texts:
        body = {"model": f"models/{_EMBED_MODEL}",
                "content": {"parts": [{"text": t}]},
                "taskType": task_type,
                "outputDimensionality": _EMBED_DIMS}
        for key_i, key in enumerate(config.GEMINI_API_KEYS):
            if (key, _EMBED_MODEL) in _dead:
                continue
            _throttle()
            r = requests.post(url, json=body, timeout=45,
                              headers={"x-goog-api-key": key,
                                       "Content-Type": "application/json"})
            if r.status_code == 429:
                _dead.add((key, _EMBED_MODEL))
                print(f"  ⚠ gemini key #{key_i + 1}: embedding quota exhausted, switching")
                continue
            r.raise_for_status()
            out.append(r.json()["embedding"]["values"])
            break
        else:
            raise GeminiUnavailable("embedding quota exhausted on all keys")
    return out
