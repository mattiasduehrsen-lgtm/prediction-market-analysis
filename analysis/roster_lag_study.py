"""Roster-news lag study — does the market reprice roster news slowly? (2026-07-20)

THE QUESTION that decides whether the news-harvester gets built: when roster/
stand-in/lineup news becomes public, how long until the Polymarket book for the
affected match repricies, and by how much?

METHOD (conservative by construction):
  - News events = Liquipedia revision timestamps (CS2 + LoL wikis, July) on
    pages matching teams in our captured markets, with roster-ish edit
    comments/titles. The wiki is the SLOW public channel — it lags the original
    announcement (tweet/Discord). Therefore any market reprice that happens
    AFTER the wiki edit was a-fortiori beatable by a faster watcher; reprices
    BEFORE the edit count against us. We measure against the slow channel and
    only claim what it supports.
  - Market reaction: from output/price_capture book snapshots (60s cadence).
    baseline mid = median over [event-90m, event-10m]; TRIGGER = first
    |mid - baseline| >= 0.05 within [event, event+6h]; lag = trigger - event.
  - PLACEBO CONTROL: identical measurement at pseudo-event times (event-5h,
    event-9h, event+14h when books allow) on the SAME market. Pre-match mids
    drift anyway; the edge claim requires trigger-rate(event) >> trigger-rate
    (placebo). Without this the study is numerology.

Liquipedia etiquette: descriptive UA, 1 request / 2s (their API terms).

Stages: fetch (revisions -> parquet), measure (join vs capture), all default.
Run (LAPTOP - full capture lives there):
  .venv\\Scripts\\python.exe -u analysis\\roster_lag_study.py
Output: output/roster_lag/{revisions.parquet, events_measured.parquet} + report.
"""
import glob
import json
import re
import sys
import time
from bisect import bisect_left, bisect_right
from pathlib import Path

import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "analysis"))
from tape_backfill import _norm, universe   # csgo-suffix-aware normalization

OUT = ROOT / "output" / "roster_lag"
OUT.mkdir(parents=True, exist_ok=True)
CAP = ROOT / "output" / "price_capture"

WIKIS = {"cs2": "https://liquipedia.net/counterstrike/api.php",
         "lol": "https://liquipedia.net/leagueoflegends/api.php"}
SINCE = "2026-07-01T00:00:00Z"
ROSTER_RE = re.compile(
    r"roster|stand-?in|substitut|benched|inactive|loan|transfer|join|leav|"
    r"sign|part ways|removed|added|coach|lineup|player", re.I)
MOVE_C = 0.05            # trigger threshold on the mid
BASE_LO, BASE_HI = 360, 10       # baseline window, minutes before event
                                 # (capture round-robins far-from-start markets
                                 #  sparsely; 6h window tolerates that)
POST_H = 6.0             # reaction window after event, hours
PLACEBO_OFFS = (-5 * 3600, -9 * 3600, +14 * 3600)

S = requests.Session()
S.headers["User-Agent"] = "prediction-market-analysis roster-lag study (contact: repo owner; read-only research)"


def stage_fetch():
    rows = []
    for game, api in WIKIS.items():
        cont = {}
        n_req = 0
        while True:
            params = {"action": "query", "list": "recentchanges", "format": "json",
                      "rcend": SINCE,      # backwards from now until July 1
                      "rcprop": "title|timestamp|comment|ids",
                      "rcnamespace": 0, "rclimit": 500, **cont}
            r = S.get(api, params=params, timeout=30)
            n_req += 1
            if r.status_code != 200:
                print(f"  [{game}] HTTP {r.status_code}; stopping this wiki")
                break
            j = r.json()
            for c in j.get("query", {}).get("recentchanges", []):
                rows.append(dict(game=game, title=c.get("title", ""),
                                 ts=c.get("timestamp", ""),
                                 comment=c.get("comment", "")))
            cont = j.get("continue") or {}
            if not cont:
                break
            if n_req % 10 == 0:
                print(f"  [{game}] {n_req} requests, {len(rows)} revisions so far")
            time.sleep(2.0)          # Liquipedia rate policy
        print(f"[fetch] {game}: total revisions {sum(1 for x in rows if x['game'] == game)}")
    df = pd.DataFrame(rows)
    df.to_parquet(OUT / "revisions.parquet", index=False)
    print(f"[fetch] saved {len(df):,} revisions")


def load_books():
    """(cid -> dict(slug, outcome, ts[], mid[])) for series markets, from capture."""
    from esports_fade_bot import is_single_map_market
    series = {}
    for fp in sorted(glob.glob(str(CAP / "prices_2026*.jsonl"))):
        with open(fp, encoding="utf-8") as fh:
            for line in fh:
                if '"slug": "cs2' not in line and '"slug": "csgo' not in line \
                        and '"slug": "lol' not in line and '"slug": "league' not in line:
                    continue
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                if e.get("prop") or e.get("bid") is None or e.get("ask") is None:
                    continue
                if is_single_map_market(e["slug"]):
                    continue
                d = series.setdefault(e["cid"], dict(slug=e["slug"], outcome=e["outcome"],
                                                     ts=[], mid=[]))
                d["ts"].append(e["ts"])
                d["mid"].append((e["bid"] + e["ask"]) / 2)
    for d in series.values():
        order = np.argsort(d["ts"])
        d["ts"] = np.asarray(d["ts"])[order]
        d["mid"] = np.asarray(d["mid"])[order]
    print(f"[books] series markets with quotes: {len(series)}")
    return series


def measure_one(d, ev_ts):
    """(baseline_n, trigger_lag_min|None, max_move) or None if books insufficient."""
    ts, mid = d["ts"], d["mid"]
    b0 = bisect_left(ts, ev_ts - BASE_LO * 60)
    b1 = bisect_right(ts, ev_ts - BASE_HI * 60)
    if b1 - b0 < 2:
        return None
    base = float(np.median(mid[b0:b1]))
    p0 = bisect_left(ts, ev_ts)
    p1 = bisect_right(ts, ev_ts + POST_H * 3600)
    if p1 - p0 < 3:
        return None
    post = mid[p0:p1]
    dev = np.abs(post - base)
    hit = np.nonzero(dev >= MOVE_C)[0]
    lag = (ts[p0 + hit[0]] - ev_ts) / 60.0 if len(hit) else None
    return (b1 - b0, lag, float(dev.max()))


def stage_measure():
    rev = pd.read_parquet(OUT / "revisions.parquet")
    rev["ets"] = pd.to_datetime(rev.ts, utc=True, errors="coerce").astype("int64") / 1e9
    rev = rev.dropna(subset=["ets"])
    uni = universe()
    team_norms = {}
    for r in uni.itertuples(index=False):
        for o in r.outcomes:
            n = _norm(o)
            if len(n) >= 3:
                team_norms.setdefault(n, o)
    print(f"[measure] {len(team_norms)} distinct team norms from captured universe")

    # roster-ish revisions whose TITLE matches a captured team
    def title_team(t):
        n = _norm(str(t).split("/")[0])
        if n in team_norms:
            return n
        for k in team_norms:
            if len(n) >= 4 and (n.startswith(k) or k.startswith(n)) and min(len(k), len(n)) / max(len(k), len(n)) >= 0.6:
                return k
        return None
    rev["team"] = rev.title.map(title_team)
    rosterish = (rev.comment.str.contains(ROSTER_RE, na=False)
                 | rev.title.str.contains(ROSTER_RE, na=False))
    cand = rev[rev.team.notna() & rosterish].copy()
    # transfer-portal / news pages: team appears in the COMMENT, not the title
    import re as _re
    long_norms = {k: v for k, v in team_norms.items() if len(k) >= 5}
    def comment_team(c):
        n = _norm(str(c))
        for k in long_norms:
            if k in n:
                return k
        return None
    extra = rev[rev.team.isna() & rosterish].copy()
    extra["team"] = extra.comment.map(comment_team)
    extra = extra[extra.team.notna()]
    print(f"[measure] +{len(extra)} events via comment-mention (transfer/news pages)")
    cand = pd.concat([cand, extra], ignore_index=True)
    # dedupe: one event per (team, hour)
    cand["hour"] = (cand.ets // 3600).astype(int)
    cand = cand.sort_values("ets").drop_duplicates(["team", "hour"])
    print(f"[measure] candidate roster events on captured teams: {len(cand)}")

    books = load_books()
    # map team norm -> cids (either outcome side)
    team_cids = {}
    slug_outcomes = {}
    for r in uni.itertuples(index=False):
        for o in r.outcomes:
            team_cids.setdefault(_norm(o), []).append(r.condition_id)
        slug_outcomes[r.condition_id] = r.slug
    rows, near_misses = [], []
    for ev in cand.itertuples(index=False):
        for cid in team_cids.get(ev.team, []):
            d = books.get(cid)
            if d is None:
                continue
            m = measure_one(d, ev.ets)
            if m is None:
                # diagnostic: how far is the nearest snapshot from the event?
                ts = d["ts"]
                if len(ts):
                    i = min(range(len(ts)), key=lambda j: abs(ts[j] - ev.ets))
                    near_misses.append(abs(ts[i] - ev.ets) / 3600)
                continue
            base_n, lag, mx = m
            placebo = []
            for off in PLACEBO_OFFS:
                pm = measure_one(d, ev.ets + off)
                if pm is not None:
                    placebo.append(pm[1] is not None)
            rows.append(dict(team=ev.team, title=ev.title, comment=str(ev.comment)[:80],
                             ev_ts=ev.ets, slug=d["slug"], cid=cid,
                             lag_min=lag, max_move=mx,
                             triggered=lag is not None,
                             placebo_n=len(placebo), placebo_hits=sum(placebo)))
    m = pd.DataFrame(rows)
    m.to_parquet(OUT / "events_measured.parquet", index=False)
    if not len(m):
        print("[measure] no events with sufficient book coverage — report n=0 honestly")
        if near_misses:
            nm = pd.Series(near_misses)
            print(f"  diagnostics: {len(nm)} event-market pairs had SOME books; "
                  f"nearest-snapshot gap hours: median {nm.median():.1f}, min {nm.min():.1f}")
        return
    trig = m[m.triggered]
    p_rate = m.placebo_hits.sum() / max(m.placebo_n.sum(), 1)
    print(f"\n[REPORT] events with book coverage: {len(m)} "
          f"({m.team.nunique()} teams, {m.cid.nunique()} markets)")
    print(f"  triggered >= {MOVE_C:.0%} move within {POST_H:.0f}h: "
          f"{len(trig)}/{len(m)} = {len(trig)/len(m):.0%}")
    print(f"  PLACEBO trigger rate (same markets, offset times): {p_rate:.0%} "
          f"({m.placebo_hits.sum()}/{m.placebo_n.sum()})")
    if len(trig):
        print(f"  lag minutes: median {trig.lag_min.median():.0f}, "
              f"q25 {trig.lag_min.quantile(.25):.0f}, q75 {trig.lag_min.quantile(.75):.0f}")
        print(f"  max move among triggered: median {trig.max_move.median():.2f}, "
              f"mean {trig.max_move.mean():.2f}")
        print("\n  triggered events (top 12 by move):")
        cols = ["team", "slug", "lag_min", "max_move", "comment"]
        print(trig.nlargest(12, "max_move")[cols].to_string(index=False))
    print("\nVERDICT INPUTS: edge plausible only if trigger-rate >> placebo-rate "
          "AND median lag is minutes+, not seconds. Wiki timestamps LAG the true "
          "announcement, so positive lags here are a-fortiori beatable; a null "
          "result here does NOT rule out tweet-time edges (wiki may be too slow "
          "a proxy) — state either way honestly.")


if __name__ == "__main__":
    stages = sys.argv[1:] or ["fetch", "measure"]
    for s in stages:
        {"fetch": stage_fetch, "measure": stage_measure}[s]()
