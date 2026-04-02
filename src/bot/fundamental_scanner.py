"""
Fundamental scanner — research-backed probability estimates for prediction markets.

For each top Polymarket market:
  1. Search Tavily for current news on the topic
  2. Ask Claude to estimate the true probability given the news
  3. Compare to market price — large gaps are fundamental signals

Results are cached to output/paper_trading/polymarket/fundamental_signals.json
and read by polymarket.py when scoring signals.

Run schedule: every FUNDAMENTAL_SCAN_INTERVAL_MINUTES minutes (default 30),
triggered from the paper_loop in main.py.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
CACHE_PATH = _PROJECT_ROOT / "output/paper_trading/polymarket/fundamental_signals.json"

# How many top markets to scan each run
SCAN_TOP_N = int(os.environ.get("FUNDAMENTAL_SCAN_TOP_N", "30"))
# Minimum gap between Claude estimate and market price to be a signal
MIN_FUNDAMENTAL_EDGE = float(os.environ.get("FUNDAMENTAL_MIN_EDGE", "0.06"))
# Cache TTL — don't re-research a market more often than this
CACHE_TTL_MINUTES = float(os.environ.get("FUNDAMENTAL_CACHE_TTL_MINUTES", "25"))


def _search_news(query: str, max_results: int = 5) -> list[dict[str, Any]]:
    """Search Tavily for recent news on a topic. Returns list of {title, content, url}."""
    from tavily import TavilyClient
    client = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])
    try:
        resp = client.search(
            query=query,
            search_depth="basic",
            max_results=max_results,
            include_answer=True,
            days=7,  # last 7 days only
        )
        results = []
        if resp.get("answer"):
            results.append({"title": "Summary", "content": resp["answer"], "url": ""})
        for r in resp.get("results", []):
            results.append({
                "title": r.get("title", ""),
                "content": r.get("content", "")[:600],
                "url": r.get("url", ""),
            })
        return results
    except Exception as exc:
        print(f"[FUNDAMENTAL] Tavily search error for '{query}': {exc}")
        return []


def _build_search_query(question: str) -> str:
    """Convert a prediction market question into a good news search query."""
    # Strip common prediction market boilerplate
    import re
    q = question.strip()
    # Remove "Will X" -> "X"
    q = re.sub(r"^Will\s+", "", q, flags=re.IGNORECASE)
    # Remove trailing "?" and "before YEAR", "by YEAR"
    q = re.sub(r"\s+(before|by)\s+\d{4}\??$", "", q, flags=re.IGNORECASE)
    q = q.rstrip("?").strip()
    return q


def _estimate_probability(question: str, market_price: float, news: list[dict]) -> dict[str, Any] | None:
    """Ask Claude to estimate probability given question + news. Returns estimate dict or None."""
    import anthropic

    if not news:
        return None

    news_text = "\n\n".join(
        f"[{i+1}] {r['title']}\n{r['content']}"
        for i, r in enumerate(news)
        if r["content"]
    )
    if not news_text.strip():
        return None

    prompt = (
        f"You are a superforecaster estimating the probability of a prediction market outcome.\n\n"
        f"Question: \"{question}\"\n"
        f"Current market price (implied probability): {market_price:.2%}\n\n"
        f"Recent news (last 7 days):\n{news_text}\n\n"
        f"Based solely on the evidence above, estimate the true probability this resolves YES.\n"
        f"Be calibrated and precise. Do not hedge — give a single number.\n\n"
        f"Respond with JSON only:\n"
        f"{{\"probability\": 0.XX, \"confidence\": \"low|medium|high\", \"reasoning\": \"one sentence\"}}"
    )

    client = anthropic.Anthropic()
    try:
        resp = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.content[0].text.strip()
        import re
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            return None
        data = json.loads(m.group())
        return {
            "probability": float(data["probability"]),
            "confidence": str(data.get("confidence", "low")),
            "reasoning": str(data.get("reasoning", "")),
        }
    except Exception as exc:
        print(f"[FUNDAMENTAL] Claude estimate error: {exc}")
        return None


def run(markets_df=None) -> dict[str, Any]:
    """
    Scan top markets for fundamental mispricings.

    markets_df: optional DataFrame with columns [question, market_price, liquidity, condition_id].
                If None, loads from the last saved signals.csv.

    Returns dict of condition_id -> fundamental signal data, also saved to CACHE_PATH.
    """
    import pandas as pd

    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Load existing cache
    cache: dict[str, Any] = {}
    if CACHE_PATH.exists():
        try:
            cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except Exception:
            cache = {}

    # Load markets if not provided
    if markets_df is None:
        signals_path = _PROJECT_ROOT / "output/paper_trading/polymarket/signals.csv"
        if not signals_path.exists():
            print("[FUNDAMENTAL] No signals.csv found — skipping scan")
            return cache
        try:
            markets_df = pd.read_csv(signals_path)
        except Exception as exc:
            print(f"[FUNDAMENTAL] Could not load signals.csv: {exc}")
            return cache

    required = {"question", "market_price", "liquidity"}
    if not required.issubset(markets_df.columns):
        print(f"[FUNDAMENTAL] signals.csv missing columns: {required - set(markets_df.columns)}")
        return cache

    # Pick top N by liquidity, active markets only
    df = markets_df.copy()
    if "active" in df.columns:
        df = df[df["active"] == True]
    if "closed" in df.columns:
        df = df[df["closed"] == False]
    df = df.sort_values("liquidity", ascending=False).head(SCAN_TOP_N)

    now_ts = time.time()
    ttl_seconds = CACHE_TTL_MINUTES * 60
    scanned = 0
    signals_found = 0

    for _, row in df.iterrows():
        question = str(row.get("question", "")).strip()
        if not question:
            continue

        market_price = float(row.get("market_price", 0.5))
        condition_id = str(row.get("condition_id", question[:60]))

        # Skip if cache is fresh
        cached = cache.get(condition_id, {})
        cached_at = cached.get("scanned_at", 0)
        if now_ts - cached_at < ttl_seconds:
            continue

        print(f"[FUNDAMENTAL] Researching: {question[:80]}")
        search_query = _build_search_query(question)
        news = _search_news(search_query)

        if not news:
            cache[condition_id] = {
                "question": question,
                "market_price": market_price,
                "fundamental_probability": None,
                "fundamental_edge": 0.0,
                "confidence": "none",
                "reasoning": "no news found",
                "is_signal": False,
                "scanned_at": now_ts,
                "scanned_at_iso": datetime.now(timezone.utc).isoformat(),
            }
            scanned += 1
            time.sleep(0.5)
            continue

        estimate = _estimate_probability(question, market_price, news)

        if estimate is None:
            cache[condition_id] = {
                "question": question,
                "market_price": market_price,
                "fundamental_probability": None,
                "fundamental_edge": 0.0,
                "confidence": "none",
                "reasoning": "estimate failed",
                "is_signal": False,
                "scanned_at": now_ts,
                "scanned_at_iso": datetime.now(timezone.utc).isoformat(),
            }
        else:
            prob = estimate["probability"]
            edge = prob - market_price
            is_signal = (
                edge >= MIN_FUNDAMENTAL_EDGE
                and estimate["confidence"] in ("medium", "high")
            )
            if is_signal:
                signals_found += 1
                print(
                    f"[FUNDAMENTAL] SIGNAL: {question[:60]} | "
                    f"market={market_price:.2%} claude={prob:.2%} edge={edge:+.2%} "
                    f"conf={estimate['confidence']}"
                )
            cache[condition_id] = {
                "question": question,
                "market_price": market_price,
                "fundamental_probability": prob,
                "fundamental_edge": round(edge, 4),
                "confidence": estimate["confidence"],
                "reasoning": estimate["reasoning"],
                "is_signal": is_signal,
                "scanned_at": now_ts,
                "scanned_at_iso": datetime.now(timezone.utc).isoformat(),
            }

        scanned += 1
        # Pace requests — Tavily free tier allows ~1 req/s
        time.sleep(1.2)

    CACHE_PATH.write_text(json.dumps(cache, indent=2), encoding="utf-8")
    print(
        f"[FUNDAMENTAL] Done. Scanned {scanned} markets, {signals_found} signals. "
        f"Cache total: {len(cache)} entries."
    )
    return cache


def load_signals() -> dict[str, Any]:
    """Load the cached fundamental signals (called by polymarket.py each cycle)."""
    if not CACHE_PATH.exists():
        return {}
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
