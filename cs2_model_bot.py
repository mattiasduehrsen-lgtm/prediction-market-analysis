"""CS2 Elo model — PAPER betting bot.

For each upcoming CS2 series market (starting within the next ~15 min), compute
the Elo model win-probability, compare to the LIVE Polymarket price, and paper-bet
the model's side when |edge| > THRESHOLD. Records the live order-book depth at
entry so we can judge whether real fills are achievable (the #1 risk).

PAPER ONLY — places no real orders. Writes output/cs2_model/paper_bets.csv.
"""
from __future__ import annotations
import csv, json, re, time
from datetime import datetime, timezone, timedelta
from pathlib import Path
import requests

from cs2_model import CS2Model, norm, teq

ROOT = Path(__file__).resolve().parent
ES_MARKETS = ROOT / "cowork_snapshot" / "esports" / "clob_esports_markets.parquet"
OUT = ROOT / "output" / "cs2_model"
OUT.mkdir(parents=True, exist_ok=True)
BETS = OUT / "paper_bets.csv"
EVENTS = OUT / "events.jsonl"

EDGE_THRESHOLD = 0.10        # bet when |model_pA - market_pA| > this
START_WINDOW_MIN = 180       # bet series markets starting within this many minutes
                             # (was 15 — far too narrow; caught 0 bets in a day).
                             # We record time_to_start so near-start vs early bets
                             # can be segmented in analysis.
POLL_INTERVAL = 120
BET_USD = 10.0
CLOB = "https://clob.polymarket.com"
VS_RE = re.compile(r"\s+vs\.?\s+", re.IGNORECASE)


def classify_market(slug, question):
    """series | map | handicap | total — for tagging paper bets so we can
    measure model edge per market type."""
    s = f"{slug or ''} {question or ''}".lower()
    if "handicap" in s:
        return "handicap"
    if "total" in s or "over/under" in s or "over / under" in s:
        return "total"
    if re.search(r"\bmap\s*\d", s) or re.search(r"-game\d|-map-?\d", s):
        return "map"
    return "series"


def _clean_team(s):
    s = re.sub(r"\(.*?\)", "", s)                                   # (-2.5)
    s = re.sub(r"\s*-\s*map\s*\d+.*$", "", s, flags=re.IGNORECASE)  # - Map 1 Winner
    s = re.sub(r"\bmap\s*\d+\b.*$", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*-\s*(winner|total|handicap).*$", "", s, flags=re.IGNORECASE)
    return s.strip(" -:")


def extract_teams(question):
    """Pull the two TEAM names out of any team-vs-team CS2 market — series,
    single-map, or handicap — stripping the '(-2.5)' / '- Map 1 Winner' noise.
    Returns None for totals (Over/Under) where there are no teams."""
    if not question:
        return None
    core = question.split(": ")[-1]
    m = VS_RE.split(core)
    if len(m) != 2:
        m = VS_RE.split(question)
        if len(m) != 2:
            return None
    a, b = _clean_team(m[0]), _clean_team(m[1])
    if not a or not b or len(a) > 40 or len(b) > 40:
        return None
    return a, b


def find_token(tokens, team_name):
    """Find the (token_id, outcome_name) whose outcome matches a team name —
    fuzzy, so 'Lavked' matches an outcome like 'Lavked - Map 1 Winner'."""
    tn = norm(team_name)
    for oc, tid in tokens.items():
        if teq(tn, norm(oc)):
            return tid, oc
    return None, None

S = requests.Session()


def parse_teams(question):
    if not question: return None
    tail = question.split(": ")[-1]
    parts = VS_RE.split(tail)
    if len(parts) != 2: return None
    a, b = parts[0].strip(), parts[1].strip()
    if not a or not b or len(a) > 40 or len(b) > 40: return None
    return a, b


def load_bet_cids():
    cids = set()
    if BETS.exists():
        with BETS.open(encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                cids.add(r.get("condition_id"))
    return cids


def write_bet(row):
    new = not BETS.exists()
    cols = ["ts", "condition_id", "slug", "market_type", "game_start", "teamA", "teamB",
            "model_pA", "market_pA", "edge", "bet_side", "bet_outcome",
            "entry_price", "book_depth_usd", "time_to_start_min",
            "eloA", "eloB", "gamesA", "gamesB"]
    with BETS.open("a", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        if new: w.writeheader()
        w.writerow({k: row.get(k, "") for k in cols})


def event(ev):
    ev["ts"] = time.time()
    with EVENTS.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(ev) + "\n")


def clob_market(cid):
    try:
        r = S.get(f"{CLOB}/markets/{cid}", timeout=8)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


def clob_midpoint(token_id):
    try:
        r = S.get(f"{CLOB}/midpoint", params={"token_id": token_id}, timeout=6)
        if r.status_code == 200:
            return float(r.json().get("mid"))
    except Exception:
        pass
    return None


def clob_book(token_id):
    """Return (best_ask, depth_usd_within_2c). depth = $ of asks we could lift
    near the best ask — our liquidity reality check."""
    try:
        r = S.get(f"{CLOB}/book", params={"token_id": token_id}, timeout=6)
        if r.status_code != 200:
            return None, 0.0
        asks = r.json().get("asks") or []
        # asks: list of {price, size}; CLOB returns asks ascending? normalize
        parsed = sorted(((float(a["price"]), float(a["size"])) for a in asks),
                        key=lambda x: x[0])
        if not parsed:
            return None, 0.0
        best = parsed[0][0]
        depth = sum(p * s for p, s in parsed if p <= best + 0.02)
        return best, round(depth, 2)
    except Exception:
        return None, 0.0


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
    df["game_start"] = pd.to_datetime(df["game_start"], errors="coerce", utc=True)
    cache["df"] = df; cache["mtime"] = mt
    print(f"[cs2-bot] loaded {len(df)} cs2 markets from index")
    return df


def run():
    print("[cs2-bot] PAPER model bot starting")
    model = CS2Model()
    print(f"[cs2-bot] Elo loaded for {len(model.elo_by_id)} teams, "
          f"{len(model.name_to_id)} name keys")
    bet_cids = load_bet_cids()
    cache = {}
    last_hb = 0
    while True:
        try:
            model.maybe_reload()
            df = load_markets(cache)
            now = datetime.now(timezone.utc)
            horizon = now + timedelta(minutes=START_WINDOW_MIN)
            cand = df[(df["game_start"].notna()) & (~df["closed"].fillna(False))
                      & (df["game_start"] > now) & (df["game_start"] <= horizon)]
            n_eval = n_bet = 0
            for r in cand.itertuples(index=False):
                if r.condition_id in bet_cids:
                    continue
                # PAPER bot bets ALL team-vs-team CS2 markets — series, single-map,
                # AND handicaps — tagged by type so we can measure edge per type.
                # Totals (Over/Under) have no teams to rate and are skipped.
                mtype = classify_market(r.slug, r.question)
                teams = extract_teams(r.question)
                if not teams:
                    bet_cids.add(r.condition_id)   # totals / unparseable
                    continue
                a, b = teams
                pred = model.predict(a, b)
                if not pred or not pred.get("ok"):
                    event({"type": "skip", "cid": r.condition_id, "slug": r.slug,
                           "mtype": mtype, "reason": (pred or {}).get("reason", "no_pred")})
                    bet_cids.add(r.condition_id)  # don't re-eval endlessly
                    continue
                n_eval += 1
                # live market + price
                mkt = clob_market(r.condition_id)
                if not mkt:
                    continue
                tokens = {t.get("outcome"): t.get("token_id")
                          for t in (mkt.get("tokens") or []) if t.get("outcome")}
                # fuzzy match team -> actual market outcome (handles 'Lavked - Map 1 Winner')
                tokA, outA = find_token(tokens, a)
                tokB, outB = find_token(tokens, b)
                if not tokA or not tokB:
                    continue
                midA = clob_midpoint(tokA)
                if midA is None:
                    continue
                market_pA = midA
                model_pA = pred["model_pA"]
                edge = model_pA - market_pA
                if abs(edge) <= EDGE_THRESHOLD:
                    continue
                # bet the model's side; entry = best ask of the side we buy.
                # bet_outcome is the ACTUAL market outcome name (for resolution).
                if edge > 0:
                    side, outcome, tok = "A", outA, tokA
                else:
                    side, outcome, tok = "B", outB, tokB
                best_ask, depth = clob_book(tok)
                if best_ask is None:
                    event({"type": "skip_no_liquidity", "cid": r.condition_id, "slug": r.slug})
                    continue
                ttm = round((r.game_start - now).total_seconds() / 60, 1)
                row = {
                    "ts": time.time(), "condition_id": r.condition_id, "slug": r.slug,
                    "market_type": mtype,
                    "game_start": r.game_start.isoformat(), "teamA": a, "teamB": b,
                    "model_pA": model_pA, "market_pA": round(market_pA, 4),
                    "edge": round(edge, 4), "bet_side": side, "bet_outcome": outcome,
                    "entry_price": round(best_ask, 4), "book_depth_usd": depth,
                    "time_to_start_min": ttm,
                    "eloA": pred["eloA"], "eloB": pred["eloB"],
                    "gamesA": pred["gamesA"], "gamesB": pred["gamesB"],
                }
                write_bet(row)
                bet_cids.add(r.condition_id)
                n_bet += 1
                print(f"[cs2-bot] PAPER BET [{mtype}] {outcome} @ ask {best_ask:.2f} "
                      f"(model {model_pA:.2f} vs mkt {market_pA:.2f}, edge {edge:+.2f}) "
                      f"depth ${depth:.0f}  {a} vs {b}")
                event({"type": "paper_bet", **row})

            if time.time() - last_hb > 300:
                print(f"[cs2-bot] heartbeat: {len(cand)} upcoming in window, "
                      f"evaluated={n_eval}, bet={n_bet}, total_bets={len(bet_cids)}")
                last_hb = time.time()
        except Exception as e:
            print(f"[cs2-bot] loop error: {e}")
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    run()
