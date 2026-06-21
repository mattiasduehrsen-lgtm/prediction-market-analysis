"""Esports market monitor — detects the Polymarket x GRID esports expansion the
moment it lands, so we don't miss new opportunity (new games, LoL head-to-head
markets appearing, liquidity arriving).

Each run:
  1. Snapshots OPEN esports markets from our index, classified by game, split into
     head-to-head (fadeable) vs futures vs single-map/prop.
  2. Samples LIVE order-book depth on a few open H2H markets per game (the
     liquidity test — the thing that decides if any of this is tradeable).
  3. Best-effort gap check vs Polymarket gamma 'active' markets — flags esports-
     looking markets our slug patterns DON'T catch (so a redesigned esports page /
     new slug format can't slip past us silently).
  4. Diffs against the previous snapshot and Telegram-alerts on material changes:
     a new game, first LoL H2H market, a market-count surge, or liquidity jump.

Append-only history: output/esports_fade/esports_market_snapshots.jsonl
Designed for a daily scheduled task. Read-only w.r.t. trading.
"""
from __future__ import annotations
import json, re, time, sys
from pathlib import Path
from datetime import datetime, timezone
import requests
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
ES = ROOT / "cowork_snapshot" / "esports" / "clob_esports_markets.parquet"
OUT = ROOT / "output" / "esports_fade"
OUT.mkdir(parents=True, exist_ok=True)
HIST = OUT / "esports_market_snapshots.jsonl"
SINGLE_MAP_RE = re.compile(r"-game\d+|-map-?\d*\b|-map-", re.I)

try:
    from notify import notify
except Exception:
    def notify(*a, **k): return False


def game_of(slug: str) -> str:
    s = (slug or "").lower()
    if "vct" in s or "valorant" in s: return "valorant"
    if s.startswith(("cs2-", "csgo-")) or "-cs2" in s or "-csgo" in s: return "cs2"
    if s.startswith(("lol-", "arch-lol-", "league-")) or "league-of-legends" in s: return "lol"
    if "dota" in s: return "dota"
    if "rocket-league" in s or "rlcs" in s: return "rocketleague"
    if "overwatch" in s or "-owl-" in s: return "overwatch"
    if "rainbow" in s or "-r6-" in s or "siege" in s: return "r6"
    if "call-of-duty" in s or "-cdl-" in s: return "cod"
    return "other"


def n_team_tokens(toks):
    toks = list(toks) if toks is not None else []
    return len([t for t in toks if t.get("outcome")])


def first_token(toks):
    toks = list(toks) if toks is not None else []
    return (toks[0].get("token_id") if toks else None)


def book_depth(token_id) -> float:
    try:
        r = requests.get("https://clob.polymarket.com/book",
                         params={"token_id": str(token_id)}, timeout=6)
        if r.status_code != 200: return 0.0
        asks = sorted(((float(a["price"]), float(a["size"]))
                       for a in (r.json().get("asks") or [])), key=lambda x: x[0])
        if not asks: return 0.0
        best = asks[0][0]
        return round(sum(p * s for p, s in asks if p <= best + 0.02), 2)
    except Exception:
        return 0.0


def build_snapshot() -> dict:
    df = pd.read_parquet(ES, columns=["slug", "tokens", "game_start", "closed", "archived"])
    op = df[(~df["closed"].astype(bool)) & (~df["archived"].astype(bool))].copy()
    op["game"] = op["slug"].apply(game_of)
    op["is_h2h"] = op["tokens"].apply(lambda t: n_team_tokens(t) == 2) & ~op["slug"].str.startswith("will-")
    op["is_prop"] = op["slug"].apply(lambda s: bool(SINGLE_MAP_RE.search(s or "")))
    now = pd.Timestamp.utcnow()
    op["gs"] = pd.to_datetime(op["game_start"], errors="coerce", utc=True)

    per_game = {}
    for g, gdf in op.groupby("game"):
        if g == "other": continue
        h2h = gdf[gdf["is_h2h"] & ~gdf["is_prop"]]
        upcoming = h2h[(h2h["gs"].notna()) & (h2h["gs"] > now)]
        # sample live depth on up to 5 upcoming-or-recent H2H markets
        sample = h2h.sort_values("gs").tail(5)
        depths = [book_depth(first_token(r["tokens"])) for _, r in sample.iterrows()]
        depths = [d for d in depths if d > 0]
        per_game[g] = {
            "open": int(len(gdf)),
            "h2h_moneyline": int(len(h2h)),
            "h2h_upcoming": int(len(upcoming)),
            "futures": int(gdf["slug"].str.startswith("will-").sum()),
            "median_h2h_depth_usd": round(float(pd.Series(depths).median()), 2) if depths else 0.0,
            "depth_samples": len(depths),
        }
    return {
        "ts": time.time(),
        "date": datetime.now(timezone.utc).isoformat(),
        "total_open_esports": int(len(op[op["game"] != "other"])),
        "per_game": per_game,
    }


def gap_check() -> dict:
    """Best-effort: esports-looking ACTIVE gamma markets our index slug-patterns miss."""
    KW = ["cs2", "csgo", "valorant", "vct", "league of legends", "lol ", "dota",
          "rocket league", "rlcs", "overwatch", "rainbow six", "counter-strike",
          "esports", "grid"]
    try:
        miss = []
        for off in (0, 100, 200, 300, 400):
            r = requests.get("https://gamma-api.polymarket.com/markets",
                             params={"closed": "false", "limit": 100, "offset": off}, timeout=15)
            if r.status_code != 200: break
            ms = r.json()
            if not ms: break
            for m in ms:
                blob = (m.get("slug", "") + " " + m.get("question", "")).lower()
                if any(k in blob for k in KW):
                    slug = m.get("slug", "")
                    # would our index pattern catch it? (rough: game_of != other OR has a known token)
                    if game_of(slug) == "other":
                        miss.append(slug)
            if len(ms) < 100: break
        return {"checked": True, "missed_count": len(set(miss)), "examples": list(dict.fromkeys(miss))[:8]}
    except Exception as e:
        return {"checked": False, "error": str(e)[:100]}


def main():
    snap = build_snapshot()
    gaps = gap_check()
    snap["gap_check"] = gaps

    prev = None
    if HIST.exists():
        lines = [l for l in HIST.read_text(encoding="utf-8").splitlines() if l.strip()]
        if lines:
            try: prev = json.loads(lines[-1])
            except Exception: prev = None

    # ── alerts on material change (only when we have a prior to diff against) ─
    alerts = []
    pg, ppg = snap["per_game"], (prev or {}).get("per_game", {})
    for g, d in (pg.items() if prev is not None else []):
        pd_ = ppg.get(g, {})
        if g not in ppg and d["open"] > 0:
            alerts.append(f"NEW GAME on Polymarket: {g} ({d['open']} open, {d['h2h_moneyline']} H2H)")
        # first LoL (or any) head-to-head appearing
        if d["h2h_moneyline"] > 0 and pd_.get("h2h_moneyline", 0) == 0:
            alerts.append(f"{g.upper()} HEAD-TO-HEAD markets appeared: {d['h2h_moneyline']} (depth ~${d['median_h2h_depth_usd']})")
        # liquidity jump (mirage lifting)
        if pd_.get("median_h2h_depth_usd", 0) and d["median_h2h_depth_usd"] >= 3 * max(pd_["median_h2h_depth_usd"], 1):
            alerts.append(f"{g.upper()} H2H liquidity jumped: ${pd_['median_h2h_depth_usd']} -> ${d['median_h2h_depth_usd']}")
    if prev and snap["total_open_esports"] >= 1.5 * max(prev.get("total_open_esports", 0), 1):
        alerts.append(f"Esports market SURGE: {prev.get('total_open_esports')} -> {snap['total_open_esports']} open")
    if gaps.get("missed_count", 0) >= 5:
        alerts.append(f"Detection gap: {gaps['missed_count']} esports-looking markets our patterns MISS (e.g. {gaps.get('examples')})")

    snap["alerts"] = alerts
    with HIST.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(snap) + "\n")

    # ── print human summary ─────────────────────────────────────────────────
    print(f"=== esports market snapshot {snap['date']} ===")
    print(f"total open esports markets: {snap['total_open_esports']}")
    for g, d in sorted(pg.items(), key=lambda x: -x[1]["open"]):
        print(f"  {g:<13} open={d['open']:<4} H2H={d['h2h_moneyline']:<4} "
              f"upcoming_H2H={d['h2h_upcoming']:<3} futures={d['futures']:<3} "
              f"median_H2H_depth=${d['median_h2h_depth_usd']}")
    print(f"gap-check: {gaps}")
    if alerts:
        print("\n*** ALERTS ***")
        for a in alerts: print("  -", a)
        notify("📊 <b>Esports market change</b>\n" + "\n".join("• " + a for a in alerts),
               kind="esports_market_change", cooldown=3600)
    else:
        print("(no material change vs previous snapshot)")


if __name__ == "__main__":
    main()
