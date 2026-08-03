"""News-lag measurement (FORWARD capture) — the harvester GO/KILL. 2026-08-03.

Question: when roster/stand-in news becomes public, how long does the market
for that team's NEXT match take to reprice, and by how much?

Data (all forward-captured, dual-timestamped):
  - output/news_capture/news_*.jsonl : HLTV RSS (2min) + Liquipedia
    recentchanges (5min). Each row has item_ts (publisher's own stamp) and
    obs_ts (when WE saw it). Median obs-lag measured at 166s.
  - output/price_capture/prices_*.jsonl : book snapshots for esports markets.

Method (conservative):
  - Event = rosterish news item; event time = item_ts (the public timestamp,
    NOT our observation time — we must beat the public clock, not our own).
  - Team extraction from title/comment, normalized, matched against the
    outcome names of captured series markets.
  - Reaction: for each captured market featuring that team whose game_start is
    AFTER the event, baseline mid = median over [event-6h, event-10m];
    TRIGGER = first |mid - baseline| >= MOVE_C within [event, event+POST_H].
  - PLACEBO: same measurement at event-5h / event-9h / event+14h on the SAME
    market. The claim requires trigger-rate(event) >> trigger-rate(placebo);
    pre-match mids drift on their own and that drift is the null hypothesis.

KNOWN COVERAGE LIMITS (stated, not hidden):
  - Liquipedia legs are rate-limited (HTTP 429) from ~2026-07-28 onward, so
    wiki events effectively cover 07-20..07-27. HLTV spans the full window.
  - NewsCapture was down 8.5h on 07-31 (guard revived it).

Run (laptop): .venv\\Scripts\\python.exe -u analysis\\news_lag_forward.py
"""
import glob
import json
import re
import sys
from bisect import bisect_left, bisect_right
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "analysis"))
from tape_backfill import _norm
from esports_fade_bot import is_single_map_market

NEWS = ROOT / "output" / "news_capture"
CAP = ROOT / "output" / "price_capture"
MOVE_C = 0.05
BASE_LO_H, BASE_HI_M = 6.0, 10
POST_H = 6.0
PLACEBO_OFFS = (-5 * 3600, -9 * 3600, +14 * 3600)
STOP_WORDS = {"the", "team", "esports", "gaming", "roster", "player", "players",
              "transfers", "portal", "news", "list", "matches", "tournament"}


def load_news():
    out = []
    for fp in sorted(glob.glob(str(NEWS / "news_*.jsonl"))):
        for line in open(fp, encoding="utf-8", errors="ignore"):
            try:
                e = json.loads(line)
            except Exception:
                continue
            if not e.get("rosterish"):
                continue
            ts = e.get("item_ts") or e.get("obs_ts")
            if not ts:
                continue
            out.append({"ts": float(ts), "src": e.get("src", ""),
                        "text": f"{e.get('title', '')} {e.get('comment', '')}"})
    out.sort(key=lambda x: x["ts"])
    return out


def _load_outcomes():
    """condition_id -> [outcome names] from the market index (full team names)."""
    import pandas as pd, json as _json
    mk = pd.read_parquet(ROOT / "cowork_snapshot" / "esports" / "clob_esports_markets.parquet",
                         columns=["condition_id", "tokens"])
    out = {}
    for r in mk.itertuples(index=False):
        try:
            toks = _json.loads(r.tokens) if isinstance(r.tokens, str) else list(r.tokens)
            names = [t.get("outcome") for t in toks if isinstance(t.get("outcome"), str)]
        except Exception:
            names = []
        if names:
            out[r.condition_id] = names
    return out


OUTCOMES = {}


def load_books():
    """cid -> {slug, tokens:[outcome names], gs, ts[], mid[]} for captured series."""
    global OUTCOMES
    if not OUTCOMES:
        OUTCOMES = _load_outcomes()
    books = {}
    for fp in sorted(glob.glob(str(CAP / "prices_*.jsonl"))):
        for line in open(fp, encoding="utf-8", errors="ignore"):
            if '"prop": 1' in line:
                continue
            try:
                e = json.loads(line)
            except Exception:
                continue
            slug = e.get("slug", "")
            if not slug.lower().startswith(("cs2-", "csgo-", "lol-", "league-")):
                continue
            if is_single_map_market(slug) or e.get("bid") is None or e.get("ask") is None:
                continue
            d = books.setdefault(e["cid"], {"slug": slug, "gs": e.get("gs"),
                                            "ts": [], "mid": []})
            d["ts"].append(e["ts"])
            d["mid"].append((e["bid"] + e["ask"]) / 2)
    import pandas as pd
    for cid, d in books.items():
        o = np.argsort(d["ts"])
        d["ts"] = np.asarray(d["ts"])[o]
        d["mid"] = np.asarray(d["mid"])[o]
        # v2 FIX: slugs use abbreviations (100t, 3dmax, 9zg) while news uses full
        # names -> zero overlap. Use the market's real OUTCOME NAMES from the
        # index instead. This was the reason the first run returned n=0.
        d["tokens"] = OUTCOMES.get(cid, [])
        gs = d.get("gs")
        d["gs_ts"] = pd.Timestamp(gs).timestamp() if gs else None
    return books


def measure(d, ev_ts):
    ts, mid = d["ts"], d["mid"]
    b0 = bisect_left(ts, ev_ts - BASE_LO_H * 3600)
    b1 = bisect_right(ts, ev_ts - BASE_HI_M * 60)
    if b1 - b0 < 2:
        return None
    base = float(np.median(mid[b0:b1]))
    p0, p1 = bisect_left(ts, ev_ts), bisect_right(ts, ev_ts + POST_H * 3600)
    if p1 - p0 < 3:
        return None
    dev = np.abs(mid[p0:p1] - base)
    hit = np.nonzero(dev >= MOVE_C)[0]
    lag = (ts[p0 + hit[0]] - ev_ts) / 60.0 if len(hit) else None
    return lag, float(dev.max())


def main():
    news, books = load_news(), load_books()
    print(f"[data] rosterish news events: {len(news)} | captured series markets: {len(books)}")
    if not news or not books:
        print("insufficient data"); return

    rows, placebo_hits, placebo_n = [], 0, 0
    for ev in news:
        raw = _norm(ev["text"])          # whole headline, normalized
        if len(raw) < 4:
            continue
        for cid, d in books.items():
            # market must involve a mentioned team AND start after the event
            if d["gs_ts"] is None or d["gs_ts"] < ev["ts"]:
                continue
            # a team matches if its normalized full name appears in the
            # normalized headline (substring) - handles "TDK transfer to 1win"
            names = [_norm(t) for t in d["tokens"]]
            if not any(len(n) >= 4 and n in raw for n in names):
                continue
            m = measure(d, ev["ts"])
            if m is None:
                continue
            lag, mx = m
            rows.append({"slug": d["slug"], "src": ev["src"], "lag": lag, "move": mx})
            for off in PLACEBO_OFFS:
                pm = measure(d, ev["ts"] + off)
                if pm is not None:
                    placebo_n += 1
                    placebo_hits += pm[0] is not None

    print(f"[join] event x market pairs with usable books: {len(rows)}")
    if not rows:
        print("\nRESULT: n=0 — no rosterish news event lands on a captured market "
              "with book coverage before its match. Report honestly; do not "
              "interpret as evidence either way.")
        return
    trig = [r for r in rows if r["lag"] is not None]
    print(f"  triggered (>= {MOVE_C:.0%} move within {POST_H:.0f}h): "
          f"{len(trig)}/{len(rows)} = {len(trig)/len(rows):.0%}")
    if placebo_n:
        print(f"  PLACEBO trigger rate: {placebo_hits}/{placebo_n} = {placebo_hits/placebo_n:.0%}")
    if trig:
        lags = sorted(r["lag"] for r in trig)
        print(f"  lag minutes: median {lags[len(lags)//2]:.0f} | "
              f"q25 {lags[len(lags)//4]:.0f} | q75 {lags[3*len(lags)//4]:.0f}")
        print(f"  max move (triggered): median {np.median([r['move'] for r in trig]):.3f}")
        print("\n  sample triggered events:")
        for r in sorted(trig, key=lambda x: -x["move"])[:8]:
            print(f"    {r['slug'][:44]:44} lag {r['lag']:6.0f}m  move {r['move']:.3f}  {r['src']}")
    print("\nGATE: harvester is worth building only if trigger-rate >> placebo-rate "
          "AND median lag is minutes+ (time to actually act).")


if __name__ == "__main__":
    main()
