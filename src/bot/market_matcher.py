"""
LLM-based market pair verification.

Runs once daily (or on demand) to build a verified_pairs.json cache that maps
Polymarket question text → its confirmed Kalshi counterpart.  The bot reads
this cache at runtime instead of relying solely on weak keyword matching.

Usage:
    .venv/Scripts/python.exe -u main.py match-markets
    .venv/Scripts/python.exe -u main.py match-markets --force
"""
from __future__ import annotations

import json
import math
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

# Cache lives alongside the other bot output files.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
CACHE_PATH = _PROJECT_ROOT / "output/paper_trading/polymarket/verified_pairs.json"
DATA_ROOT   = _PROJECT_ROOT / "data/current"

BATCH_SIZE        = 15    # pairs per LLM call
MAX_CANDIDATES    = 5     # top candidates per Polymarket market sent to the LLM
MIN_PREFILTER     = 0.15  # keyword overlap floor before LLM consideration
MIN_LLM_CONF      = 0.70  # minimum LLM confidence to accept a pair
CACHE_TTL_HOURS   = 24    # hours before a cache entry is considered stale
MAX_POLY_MARKETS  = 600   # cap to keep runtime reasonable


# ── Helpers ───────────────────────────────────────────────────────────────────

def _col(df: pd.DataFrame, *candidates: str) -> str | None:
    """Return the first candidate column name that exists in df, else None."""
    for c in candidates:
        if c in df.columns:
            return c
    return None


def _keyword_overlap(a: str, b: str) -> float:
    """Fast word-overlap ratio used as a cheap pre-filter before calling the LLM."""
    stop = {
        "will", "the", "a", "an", "of", "in", "on", "at", "to", "for",
        "is", "are", "be", "by", "who", "what", "when", "which", "or",
        "and", "if", "this", "that", "it", "its", "was", "has", "have",
    }
    wa = set(re.sub(r"[^a-z0-9 ]", " ", a.lower()).split()) - stop
    wb = set(re.sub(r"[^a-z0-9 ]", " ", b.lower()).split()) - stop
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / min(len(wa), len(wb))


# ── Data loading ──────────────────────────────────────────────────────────────

def _load_poly_markets() -> pd.DataFrame:
    path = DATA_ROOT / "polymarket/markets.parquet"
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_parquet(path)
    q_col = _col(df, "question", "title", "description")
    if q_col is None:
        return pd.DataFrame()
    if q_col != "question":
        df = df.rename(columns={q_col: "question"})
    return df


def _load_kalshi_markets() -> pd.DataFrame:
    path = DATA_ROOT / "kalshi/markets.parquet"
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_parquet(path)
    # Normalise column names to what _merge_cross_market_data expects.
    q_col  = _col(df, "kalshi_question", "question", "title")
    tk_col = _col(df, "kalshi_ticker", "ticker", "market_ticker")
    vol_col = _col(df, "kalshi_volume", "volume", "dollar_volume")
    if q_col is None:
        return pd.DataFrame()
    renames: dict[str, str] = {}
    if q_col  != "kalshi_question": renames[q_col]  = "kalshi_question"
    if tk_col and tk_col != "kalshi_ticker": renames[tk_col] = "kalshi_ticker"
    if vol_col and vol_col != "kalshi_volume": renames[vol_col] = "kalshi_volume"
    if renames:
        df = df.rename(columns=renames)
    return df


# ── Candidate pre-filtering ───────────────────────────────────────────────────

def _top_candidates(
    poly_question: str,
    kalshi_records: list[dict[str, Any]],
    top_k: int = MAX_CANDIDATES,
) -> list[dict[str, Any]]:
    """Return the top-k Kalshi records by keyword overlap with poly_question."""
    scored = [
        (rec, _keyword_overlap(poly_question, str(rec.get("kalshi_question", ""))))
        for rec in kalshi_records
    ]
    scored = [(r, s) for r, s in scored if s >= MIN_PREFILTER]
    scored.sort(key=lambda x: x[1], reverse=True)
    return [r for r, _ in scored[:top_k]]


# ── LLM verification ─────────────────────────────────────────────────────────

def _verify_batch(pairs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Call Claude Haiku to verify whether each pair asks about the same event.

    pairs:   [{"poly_question": ..., "kalshi_question": ..., "poly_key": ...,
               "kalshi_question_raw": ..., "kalshi_ticker": ...}, ...]
    returns: same list enriched with "match", "confidence", "reason".
    """
    import anthropic

    numbered = "\n\n".join(
        f'Pair {i + 1}:\n  Polymarket: "{p["poly_question"]}"\n  Kalshi:     "{p["kalshi_question"]}"'
        for i, p in enumerate(pairs)
    )

    prompt = (
        "You are verifying prediction market pairs.\n"
        "For each pair determine if BOTH questions resolve YES/NO based on the "
        "EXACT SAME underlying real-world outcome.\n\n"
        + numbered
        + '\n\nRespond ONLY with a JSON array — one object per pair, in order:\n'
        '[{"pair":1,"match":true,"confidence":0.95,"reason":"both track X"},…]\n\n'
        "Rules:\n"
        '- "match":true only when the same event outcome decides both questions\n'
        "- Different thresholds, dates, or entities → match=false\n"
        '- "confidence" reflects how certain you are (0.0–1.0)\n'
        '- "reason" is one short sentence'
    )

    client = anthropic.Anthropic()
    resp = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = resp.content[0].text.strip()

    # Extract the JSON array robustly.
    m = re.search(r"\[.*\]", raw, re.DOTALL)
    if not m:
        return []

    try:
        results: list[dict] = json.loads(m.group())
    except json.JSONDecodeError:
        return []

    out: list[dict[str, Any]] = []
    for r in results:
        idx = int(r.get("pair", 0)) - 1
        if 0 <= idx < len(pairs):
            p = pairs[idx]
            out.append({
                **p,
                "match":      bool(r.get("match", False)),
                "confidence": float(r.get("confidence", 0.0)),
                "reason":     str(r.get("reason", "")),
            })
    return out


# ── Main entry point ──────────────────────────────────────────────────────────

def run(force: bool = False) -> None:
    """
    Build or refresh the verified_pairs.json cache.

    force=True ignores the TTL and re-verifies everything.
    """
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Load existing cache.
    cache: dict[str, Any] = {}
    if CACHE_PATH.exists():
        try:
            cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except Exception:
            cache = {}

    poly_df   = _load_poly_markets()
    kalshi_df = _load_kalshi_markets()

    if poly_df.empty:
        print("[MATCHER] No Polymarket data found — run data collection first")
        return
    if kalshi_df.empty:
        print("[MATCHER] No Kalshi data found — run data collection first")
        return

    # Sort Kalshi by volume so we match against the most liquid markets first.
    if "kalshi_volume" in kalshi_df.columns:
        kalshi_df = kalshi_df.sort_values("kalshi_volume", ascending=False)
    kalshi_records: list[dict[str, Any]] = kalshi_df.to_dict("records")

    # Cap Polymarket to most relevant markets.
    if len(poly_df) > MAX_POLY_MARKETS:
        poly_df = poly_df.head(MAX_POLY_MARKETS)

    now = datetime.now(timezone.utc).isoformat()
    skipped = 0
    to_verify: list[dict[str, Any]] = []   # flat list of candidate pairs

    for _, row in poly_df.iterrows():
        question = str(row.get("question", "")).strip()
        if not question:
            continue

        key = question.lower().strip()

        # Skip if fresh enough and not forcing.
        if not force and key in cache:
            entry = cache[key]
            try:
                age_h = (
                    datetime.now(timezone.utc)
                    - datetime.fromisoformat(entry.get("verified_at", "2000-01-01T00:00:00+00:00"))
                ).total_seconds() / 3600
                if age_h < CACHE_TTL_HOURS:
                    skipped += 1
                    continue
            except Exception:
                pass

        candidates = _top_candidates(question, kalshi_records)
        if not candidates:
            # No keyword overlap — record a no-match so we don't retry every run.
            cache[key] = {"no_match": True, "verified_at": now}
            continue

        for c in candidates:
            to_verify.append({
                "poly_key":           key,
                "poly_question":      question,
                "kalshi_question":    str(c.get("kalshi_question", "")),
                "kalshi_ticker":      str(c.get("kalshi_ticker", "")),
            })

    total_pairs = len(to_verify)
    print(
        f"[MATCHER] {skipped} markets skipped (cache fresh) | "
        f"{total_pairs} candidate pairs queued for LLM verification"
    )
    if not total_pairs:
        print("[MATCHER] Cache is up to date — nothing to do")
        return

    # Batch LLM calls.
    verified: list[dict[str, Any]] = []
    n_batches = math.ceil(total_pairs / BATCH_SIZE)
    for batch_i in range(n_batches):
        batch = to_verify[batch_i * BATCH_SIZE : (batch_i + 1) * BATCH_SIZE]
        print(f"[MATCHER] LLM batch {batch_i + 1}/{n_batches} ({len(batch)} pairs)…")
        try:
            results = _verify_batch(batch)
            verified.extend(results)
        except Exception as exc:
            # Likely a rate-limit — wait 20 s and retry once before skipping.
            print(f"[MATCHER] Batch {batch_i + 1} error ({exc}) — retrying in 20 s…")
            time.sleep(20)
            try:
                results = _verify_batch(batch)
                verified.extend(results)
                print(f"[MATCHER] Batch {batch_i + 1} retry succeeded")
            except Exception as exc2:
                print(f"[MATCHER] Batch {batch_i + 1} retry failed (skipping): {exc2}")
        # Small pause between batches to stay well under rate limits.
        time.sleep(1)

    # Keep only the best (highest-confidence) match per Polymarket question.
    best_by_key: dict[str, dict[str, Any]] = {}
    for r in verified:
        key = r["poly_key"]
        if r["match"] and r["confidence"] > best_by_key.get(key, {}).get("confidence", -1):
            best_by_key[key] = r

    # Update cache.
    new_pairs = 0
    processed_keys: set[str] = {p["poly_key"] for p in to_verify}

    for key in processed_keys:
        if key in best_by_key:
            r = best_by_key[key]
            cache[key] = {
                "kalshi_question": r["kalshi_question"],
                "kalshi_ticker":   r["kalshi_ticker"],
                "confidence":      r["confidence"],
                "reason":          r["reason"],
                "verified_at":     now,
            }
            new_pairs += 1
        else:
            # LLM found no match for any candidate.
            cache[key] = {"no_match": True, "verified_at": now}

    CACHE_PATH.write_text(json.dumps(cache, indent=2), encoding="utf-8")
    print(
        f"[MATCHER] Done. {new_pairs} verified pairs added/updated. "
        f"Cache total: {len(cache)} entries."
    )
