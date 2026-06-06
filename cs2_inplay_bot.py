"""CS2 IN-PLAY series repricing — PAPER bot.

Watches bo3.gg for live CS2 series. After a map completes, computes the model's
calibrated live series-winner probability from the current score, compares to the
LIVE Polymarket series price, and paper-bets the divergence.

Records (the two unknowns that decide if this is real):
  - bo3 detection latency (how stale our view of the map-completion is)
  - live order-book depth at our entry (can we fill at size?)

PAPER ONLY. Output: output/cs2_inplay/paper_bets.csv
"""
from __future__ import annotations
import csv, json, math, re, time
from datetime import datetime, timezone, timedelta
from pathlib import Path
import requests
import pandas as pd
from cs2_model import CS2Model, norm, teq

ROOT = Path(__file__).resolve().parent
ES_MARKETS = ROOT / "cowork_snapshot" / "esports" / "clob_esports_markets.parquet"
OUT = ROOT / "output" / "cs2_inplay"
OUT.mkdir(parents=True, exist_ok=True)
BETS = OUT / "paper_bets.csv"
EVENTS = OUT / "events.jsonl"

EDGE_THRESHOLD = 0.05
POLL_INTERVAL = 60
BET_USD = 10.0
CLOB = "https://clob.polymarket.com"
BO3 = "https://api.bo3.gg/api/v1"
VS_RE = re.compile(r"\s+vs\.?\s+", re.IGNORECASE)
SINGLE_MAP_RE = re.compile(r"-game\d+|-map-?\d*\b|-map-|handicap|total|rounds", re.IGNORECASE)
S = requests.Session()
S.headers.update({"User-Agent": "Mozilla/5.0 Chrome/120 Safari/537.36", "Accept": "application/json"})


# ---- combinatorics: P(team reaches W wins before opp, given current a-b, single-map p) ----
def series_prob(p, a, b, W):
    need_a, need_b = W - a, W - b
    if need_a <= 0: return 1.0
    if need_b <= 0: return 0.0
    tot = 0.0
    for k in range(need_b):           # opp wins k (<need_b) before A gets need_a
        tot += math.comb(need_a - 1 + k, k) * (p ** need_a) * ((1 - p) ** k)
    return tot

def invert(P, W):
    lo, hi = 0.0, 1.0
    for _ in range(40):
        m = (lo + hi) / 2
        if series_prob(m, 0, 0, W) < P: lo = m
        else: hi = m
    return (lo + hi) / 2


def bo3_get(path, params=None):
    try:
        r = S.get(f"{BO3}/{path}", params=params, timeout=12)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None

def clob_market(cid):
    try:
        r = S.get(f"{CLOB}/markets/{cid}", timeout=8)
        if r.status_code == 200: return r.json()
    except Exception: pass
    return None

def clob_midpoint(tok):
    try:
        r = S.get(f"{CLOB}/midpoint", params={"token_id": tok}, timeout=6)
        if r.status_code == 200: return float(r.json().get("mid"))
    except Exception: pass
    return None

def clob_book(tok):
    try:
        r = S.get(f"{CLOB}/book", params={"token_id": tok}, timeout=6)
        if r.status_code != 200: return None, 0.0
        asks = sorted(((float(a["price"]), float(a["size"])) for a in (r.json().get("asks") or [])),
                      key=lambda x: x[0])
        if not asks: return None, 0.0
        best = asks[0][0]
        depth = sum(p * s for p, s in asks if p <= best + 0.02)
        return best, round(depth, 2)
    except Exception:
        return None, 0.0

def event(ev):
    ev["ts"] = time.time()
    with EVENTS.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(ev) + "\n")

def parse_teams(q):
    if not q: return None
    parts = VS_RE.split(q.split(": ")[-1])
    if len(parts) != 2: return None
    a, b = parts[0].strip(), parts[1].strip()
    if not a or not b or len(a) > 40 or len(b) > 40: return None
    return a, b

def load_bet_keys():
    keys = set()
    if BETS.exists():
        for r in csv.DictReader(BETS.open(encoding="utf-8")):
            keys.add((r.get("condition_id"), r.get("score_state")))
    return keys

def write_bet(row):
    cols = ["ts", "condition_id", "slug", "teamA", "teamB", "bo_type", "score_state",
            "map1_winner", "model_pre", "p_single", "model_live", "market_live",
            "edge", "bet_side", "bet_outcome", "entry_price", "book_depth_usd",
            "bo3_detect_lag_s", "A_won_series"]
    new = not BETS.exists()
    with BETS.open("a", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        if new: w.writeheader()
        w.writerow({k: row.get(k, "") for k in cols})


def load_markets(cache):
    try:
        mt = ES_MARKETS.stat().st_mtime
    except OSError:
        return cache.get("df")
    if cache.get("mtime") == mt and cache.get("df") is not None:
        return cache["df"]
    import pandas as pd
    df = pd.read_parquet(ES_MARKETS, columns=["condition_id", "slug", "question",
                                              "game_start", "closed"])
    df = df[df["slug"].fillna("").str.startswith("cs2-")].copy()
    df = df[~df["slug"].fillna("").str.contains(SINGLE_MAP_RE)]   # series only
    df["game_start"] = pd.to_datetime(df["game_start"], errors="coerce", utc=True)
    cache["df"] = df; cache["mtime"] = mt
    print(f"[inplay] loaded {len(df)} cs2 series markets")
    return df


def find_pm_market(df, nA, nB, now):
    import pandas as pd
    win = df[(df["game_start"].notna())
             & (df["game_start"] >= now - timedelta(hours=8))
             & (df["game_start"] <= now + timedelta(hours=1))
             & (~df["closed"].fillna(False))]
    for r in win.itertuples(index=False):
        t = parse_teams(r.question)
        if not t: continue
        a, b = norm(t[0]), norm(t[1])
        if (teq(nA, a) and teq(nB, b)) or (teq(nA, b) and teq(nB, a)):
            return r, t
    return None, None


def run():
    print("[inplay] CS2 in-play PAPER bot starting")
    model = CS2Model()
    print(f"[inplay] series Elo for {len(model.elo_by_id)} teams")
    bet_keys = load_bet_keys()
    logged_detect = set()   # dedup live_detected/skip events per (teams, score)
    cache = {}
    last_hb = 0
    while True:
        try:
            model.maybe_reload()
            now = datetime.now(timezone.utc)
            # LIVE DETECTION FROM GAMES ONLY (v2). bo3's /matches endpoint sorts
            # by -start_date = future UPCOMING matches, and its id/status/range
            # filters are ignored — so we can't get live status or bo_type there.
            # Games DO carry live state + winners + timestamps. We detect
            # post-map-1 directly: exactly 1 map completed (has a winner) + a map
            # currently live. This also auto-excludes Bo1 (no live map after map1)
            # and deciders (2+ done). Assume Bo3 (W=2): ~99% of CS matches, and
            # we only bet post-map-1 where Bo3 is the validated case.
            W = 2
            games = (bo3_get("games", {"sort": "-begin_at", "page[limit]": 200}) or {}).get("results") or []
            by_match = {}
            for g in games:
                by_match.setdefault(g.get("match_id"), []).append(g)

            n_live = n_bet = 0
            for mid, gs in by_match.items():
                gs = sorted(gs, key=lambda x: x.get("number") or 0)
                done = [g for g in gs if g.get("winner_clan_name") and g.get("loser_clan_name")]
                live_g = [g for g in gs if g.get("state") in ("current", "started")]
                # post-map-1 ONLY: exactly one map decided + a map in progress
                if len(done) != 1 or not live_g:
                    continue
                n_live += 1
                g1 = done[0]
                tA = g1["winner_clan_name"].strip()   # map-1 winner -> 1-0
                tB = g1["loser_clan_name"].strip()
                aw, bw = 1, 0
                if not tA or not tB or tA == tB:
                    continue
                nA, nB = norm(tA), norm(tB)
                dkey = (nA, nB, f"{aw}-{bw}")
                first_see = dkey not in logged_detect
                if first_see:
                    logged_detect.add(dkey)
                    event({"type": "live_detected", "teamA": tA, "teamB": tB,
                           "score": f"{aw}-{bw}", "live_map": (live_g[0].get("map_name"))})
                # model pre-match series prob (oriented to tA)
                pred = model.predict(tA, tB)
                if not pred or not pred.get("ok"):
                    if first_see:
                        event({"type": "skip_model_unmatched", "teamA": tA, "teamB": tB,
                               "reason": (pred or {}).get("reason", "no_pred")})
                    continue
                model_pre_A = pred["model_pA"]
                p = invert(min(max(model_pre_A, 0.02), 0.98), W)
                model_live_A = series_prob(p, aw, bw, W)
                # find live Polymarket series market
                pm, pteams = find_pm_market(load_markets(cache), nA, nB, now)
                if pm is None:
                    if first_see:
                        event({"type": "skip_no_pm_market", "teamA": tA, "teamB": tB})
                    continue
                key = (pm.condition_id, f"{aw}-{bw}")
                if key in bet_keys:
                    continue
                # live price for the team that is tA, in the PM market
                mkt = clob_market(pm.condition_id)
                if not mkt:
                    continue
                toks = {t.get("outcome"): t.get("token_id") for t in (mkt.get("tokens") or []) if t.get("outcome")}
                # map tA -> PM outcome
                tokA = outA = None
                for oc, tid in toks.items():
                    if teq(nA, norm(oc)): tokA, outA = tid, oc
                tokB = outB = None
                for oc, tid in toks.items():
                    if teq(nB, norm(oc)): tokB, outB = tid, oc
                if not tokA or not tokB:
                    continue
                midA = clob_midpoint(tokA)
                if midA is None:
                    continue
                edge = model_live_A - midA
                if abs(edge) <= EDGE_THRESHOLD:
                    bet_keys.add(key); continue
                # bet the model's side
                if edge > 0:
                    side, outcome, tok = "A", outA, tokA
                else:
                    side, outcome, tok = "B", outB, tokB
                best_ask, depth = clob_book(tok)
                if best_ask is None:
                    event({"type": "skip_no_liquidity", "cid": pm.condition_id, "slug": pm.slug})
                    bet_keys.add(key); continue
                # bo3 detection latency: how long since the live map started (~map completion)
                lag = None
                try:
                    lag = round(time.time() - pd.Timestamp(live_g[0]["begin_at"]).timestamp(), 0)
                except Exception:
                    pass
                row = {
                    "ts": time.time(), "condition_id": pm.condition_id, "slug": pm.slug,
                    "teamA": tA, "teamB": tB, "bo_type": "3(assumed)", "score_state": f"{aw}-{bw}",
                    "map1_winner": tA if aw > bw else tB,
                    "model_pre": round(model_pre_A, 4), "p_single": round(p, 4),
                    "model_live": round(model_live_A, 4), "market_live": round(midA, 4),
                    "edge": round(edge, 4), "bet_side": side, "bet_outcome": outcome,
                    "entry_price": round(best_ask, 4), "book_depth_usd": depth,
                    "bo3_detect_lag_s": lag, "A_won_series": "",
                }
                write_bet(row); bet_keys.add(key); n_bet += 1
                print(f"[inplay] PAPER BET [{aw}-{bw}] {outcome} @ {best_ask:.2f} "
                      f"(model_live {model_live_A:.2f} vs mkt {midA:.2f}, edge {edge:+.2f}) "
                      f"depth ${depth:.0f} lag {lag}s  {tA} vs {tB}")
                event({"type": "inplay_paper_bet", **row})

            if time.time() - last_hb > 300:
                print(f"[inplay] heartbeat: live_series={n_live} bet_this_cycle={n_bet} "
                      f"total_keys={len(bet_keys)}")
                last_hb = time.time()
        except Exception as e:
            print(f"[inplay] loop error: {e}")
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    run()
