from __future__ import annotations

import csv
import json
import re
import time
from pathlib import Path

from flask import Flask, jsonify, render_template, request
from src.bot.version import PATCH, PATCH_DATE, PATCH_NOTES

# Price-tick lines: [HH:MM:SS] BTC UP=0.505 DOWN=0.495 | 179s left
_PRICE_TICK = re.compile(r"^\[\d{2}:\d{2}:\d{2}\] \w+ UP=")

OUT_5M      = Path(__file__).resolve().parents[2] / "output/5m_trading"
OUT_5M_LIVE = Path(__file__).resolve().parents[2] / "output/5m_live"
PAUSE_FLAG  = OUT_5M_LIVE / "paused.live.flag"

app = Flask(__name__)


def create_app() -> Flask:
    return app


def _read_json(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows.append(row)
    return rows


def _reset_epoch() -> float:
    p = OUT_5M / "equity_reset.json"
    try:
        return float(json.loads(p.read_text(encoding="utf-8")).get("reset_at", 0))
    except Exception:
        return 0.0


def _trades_since_reset() -> list[dict]:
    epoch = _reset_epoch()
    rows = _read_csv(OUT_5M / "trades.csv")
    if not epoch:
        return rows
    return [r for r in rows if float(r.get("closed_at") or 0) >= epoch]


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/summary")
def api_summary():
    # Aggregate per-thread summary files
    totals = {"equity": 0.0, "closed_trades": 0, "wins": 0, "losses": 0,
              "total_pnl": 0.0, "open_positions": 0, "win_pnl": 0.0, "loss_pnl": 0.0}
    found = False
    for f in OUT_5M.glob("summary*.json"):
        d = _read_json(f)
        if not d:
            continue
        found = True
        totals["closed_trades"] += int(d.get("closed_trades", 0))
        totals["wins"]          += int(d.get("wins", 0))
        totals["losses"]        += int(d.get("losses", 0))
        totals["total_pnl"]     += float(d.get("total_pnl", 0))
        totals["open_positions"]+= int(d.get("open_positions", 0))
        # avg_win/avg_loss require raw sums — recompute from trades below
    if not found:
        return jsonify({})
    ct = totals["closed_trades"]
    wins, losses = totals["wins"], totals["losses"]
    totals["equity"]   = round(totals["total_pnl"], 2)
    totals["total_pnl"]= round(totals["total_pnl"], 2)
    totals["win_rate"] = round(wins / ct * 100, 1) if ct else 0.0
    # Recompute avg_win / avg_loss from trades since reset for accuracy
    rows = _trades_since_reset()
    win_pnls  = [float(r["pnl_usd"]) for r in rows if r.get("pnl_usd") and float(r["pnl_usd"]) > 0]
    loss_pnls = [float(r["pnl_usd"]) for r in rows if r.get("pnl_usd") and float(r["pnl_usd"]) <= 0]
    totals["avg_win"]  = round(sum(win_pnls)  / len(win_pnls),  2) if win_pnls  else 0.0
    totals["avg_loss"] = round(sum(loss_pnls) / len(loss_pnls), 2) if loss_pnls else 0.0
    return jsonify(totals)


@app.route("/api/positions")
def api_positions():
    # Aggregate per-thread positions files (positions_BTC-5m-mean_reversion.csv etc.)
    rows = []
    for f in sorted(OUT_5M.glob("positions*.csv")):
        rows.extend(_read_csv(f))
    return jsonify(rows)


@app.route("/api/trades")
def api_trades():
    rows = _trades_since_reset()
    clean = [{k: v for k, v in row.items() if k is not None} for row in rows]
    return jsonify(clean[-100:])


@app.route("/api/ev")
def api_ev():
    rows = _trades_since_reset()
    # Also pull asset/strategy from raw rows for grouping
    raw_rows = rows
    trades = []
    for row in rows:
        try:
            trades.append({
                "pnl":          float(row.get("pnl_usd") or 0),
                "entry_price":  float(row.get("entry_price") or 0),
                "exit_reason":  row.get("exit_reason", ""),
                "side":         row.get("side", ""),
                "hold_seconds": float(row.get("hold_seconds") or 0),
            })
        except Exception:
            pass

    for t, r in zip(trades, raw_rows):
        t["asset"]    = r.get("asset", "BTC")
        t["strategy"] = r.get("strategy", "mean_reversion")
        t["window"]   = r.get("window", "5m")

    if not trades:
        return jsonify({})

    def ev_stats(group):
        if not group: return None
        wins   = [t for t in group if t["pnl"] > 0]
        losses = [t for t in group if t["pnl"] <= 0]
        wr     = len(wins) / len(group)
        avg_w  = sum(t["pnl"] for t in wins)   / len(wins)   if wins   else 0
        avg_l  = sum(t["pnl"] for t in losses) / len(losses) if losses else 0
        ev     = wr * avg_w + (1 - wr) * avg_l
        return {"count": len(group), "win_rate": round(wr * 100, 1),
                "avg_win": round(avg_w, 2), "avg_loss": round(avg_l, 2),
                "ev_per_trade": round(ev, 3), "total_pnl": round(sum(t["pnl"] for t in group), 2)}

    # Rolling EV — last 10 trades, 20 trades, all trades
    def rolling(n):
        return ev_stats(trades[-n:]) if len(trades) >= n else ev_stats(trades)

    # By entry price bucket — covers both mean-reversion (0.28-0.39) and momentum (~0.50)
    def bucket(p):
        if p < 0.30: return "<0.30"
        if p < 0.33: return "0.30-0.33"
        if p < 0.36: return "0.33-0.36"
        if p < 0.40: return "0.36-0.40"
        if p < 0.52: return "0.40-0.52 (momentum)"
        return ">0.52"

    by_entry = {}
    for b in ["<0.30", "0.30-0.33", "0.33-0.36", "0.36-0.40", "0.40-0.52 (momentum)", ">0.52"]:
        grp = [t for t in trades if bucket(t["entry_price"]) == b]
        s = ev_stats(grp)
        if s: by_entry[b] = s

    # By exit reason
    reasons = {}
    for r in set(t["exit_reason"] for t in trades):
        if not r: continue
        s = ev_stats([t for t in trades if t["exit_reason"] == r])
        if s: reasons[r] = s

    # By side
    by_side = {
        "UP":   ev_stats([t for t in trades if t["side"] == "UP"]),
        "DOWN": ev_stats([t for t in trades if t["side"] == "DOWN"]),
    }

    # By asset
    by_asset = {}
    for a in sorted(set(t["asset"] for t in trades)):
        s = ev_stats([t for t in trades if t["asset"] == a])
        if s: by_asset[a] = s

    # By strategy
    by_strategy = {}
    for strat in sorted(set(t["strategy"] for t in trades)):
        s = ev_stats([t for t in trades if t["strategy"] == strat])
        if s: by_strategy[strat] = s

    # By window size
    by_window = {}
    for w in sorted(set(t["window"] for t in trades)):
        s = ev_stats([t for t in trades if t["window"] == w])
        if s: by_window[w] = s

    # Rolling EV series — 20-trade sliding window
    rolling_series = []
    win_size = 20
    for i in range(win_size, len(trades) + 1):
        chunk = trades[i - win_size:i]
        s = ev_stats(chunk)
        if s:
            rolling_series.append(round(s["ev_per_trade"], 3))

    return jsonify({
        "overall":        ev_stats(trades),
        "last_20":        rolling(20),
        "last_10":        rolling(10),
        "by_entry_price": by_entry,
        "by_exit_reason": reasons,
        "by_side":        by_side,
        "by_asset":       by_asset,
        "by_strategy":    by_strategy,
        "by_window":      by_window,
        "rolling_series": rolling_series,
    })


@app.route("/api/log")
def api_log():
    """Return last 80 meaningful lines of bot.log, filtering price-tick noise."""
    log_path = Path(__file__).resolve().parents[2] / "bot.log"
    if not log_path.exists():
        return jsonify({"lines": []})
    try:
        recent = log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-2000:]
        # Keep all non-price-tick lines (events, windows, summaries, errors)
        events = [l for l in recent if not _PRICE_TICK.match(l)]
        # Append the single most recent price tick so current state is visible
        price_lines = [l for l in recent if _PRICE_TICK.match(l)]
        if price_lines:
            events.append("— " + price_lines[-1])
        return jsonify({"lines": events[-80:]})
    except Exception:
        return jsonify({"lines": []})


# ── Equity curve endpoint ─────────────────────────────────────────────────────

@app.route("/api/equity")
def api_equity():
    """Return cumulative P&L series for paper and live bots."""

    def _series(rows):
        """Sort by closed_at, return list of {t, pnl, cum_pnl, label} dicts."""
        pts = []
        for r in rows:
            try:
                pts.append((float(r["closed_at"]), float(r["pnl_usd"]),
                            r.get("asset", ""), r.get("exit_reason", "")))
            except Exception:
                pass
        pts.sort(key=lambda x: x[0])
        cum = 0.0
        out = []
        for t, pnl, asset, reason in pts:
            cum = round(cum + pnl, 4)
            out.append({"t": t, "pnl": round(pnl, 4), "cum_pnl": cum,
                        "asset": asset, "exit_reason": reason})
        return out

    # Paper — all trades since reset
    paper_rows  = _trades_since_reset()
    paper_series = _series(paper_rows)

    # Live — all trades across all tags
    live_rows = []
    for f in sorted(OUT_5M_LIVE.glob("trades*.csv")):
        live_rows.extend(_read_csv(f))
    live_series = _series(live_rows)

    return jsonify({"paper": paper_series, "live": live_series})


# ── Live trading endpoints ─────────────────────────────────────────────────────

@app.route("/api/live/summary")
def api_live_summary():
    totals = {"closed_trades": 0, "wins": 0, "losses": 0,
              "total_pnl": 0.0, "open_positions": 0}
    found = False
    for f in OUT_5M_LIVE.glob("summary*.json"):
        d = _read_json(f)
        if not d:
            continue
        found = True
        totals["closed_trades"] += int(d.get("closed_trades", 0))
        totals["wins"]          += int(d.get("wins", 0))
        totals["losses"]        += int(d.get("losses", 0))
        totals["total_pnl"]     += float(d.get("total_pnl", 0))
        totals["open_positions"]+= int(d.get("open_positions", 0))
    if not found:
        return jsonify({})
    ct = totals["closed_trades"]
    totals["win_rate"]  = round(totals["wins"] / ct * 100, 1) if ct else 0.0
    totals["total_pnl"] = round(totals["total_pnl"], 2)
    # avg win/loss from all live trades
    rows = []
    for f in sorted(OUT_5M_LIVE.glob("trades*.csv")):
        rows.extend(_read_csv(f))
    win_pnls  = [float(r["pnl_usd"]) for r in rows if r.get("pnl_usd") and float(r["pnl_usd"]) > 0]
    loss_pnls = [float(r["pnl_usd"]) for r in rows if r.get("pnl_usd") and float(r["pnl_usd"]) <= 0]
    totals["avg_win"]  = round(sum(win_pnls)  / len(win_pnls),  2) if win_pnls  else 0.0
    totals["avg_loss"] = round(sum(loss_pnls) / len(loss_pnls), 2) if loss_pnls else 0.0
    # Wallet balance — written to summary JSON by the live engine every 60s
    wallet_usdc = None
    for f in OUT_5M_LIVE.glob("summary*.json"):
        w = _read_json(f).get("wallet_usdc")
        if w is not None:
            wallet_usdc = float(w)
            break   # all threads share the same wallet; one file is enough
    if wallet_usdc is not None:
        totals["wallet_usdc"] = wallet_usdc
    return jsonify(totals)


@app.route("/api/live/positions")
def api_live_positions():
    rows = []
    for f in sorted(OUT_5M_LIVE.glob("positions*.csv")):
        rows.extend(_read_csv(f))
    return jsonify(rows)


@app.route("/api/live/trades")
def api_live_trades():
    rows = []
    for f in sorted(OUT_5M_LIVE.glob("trades*.csv")):
        rows.extend(_read_csv(f))
    clean = [{k: v for k, v in row.items() if k is not None} for row in rows]
    return jsonify(clean[-100:])


@app.route("/api/live/log")
def api_live_log():
    """Return last 80 meaningful lines of live.log."""
    log_path = Path(__file__).resolve().parents[2] / "live.log"
    if not log_path.exists():
        return jsonify({"lines": []})
    try:
        recent = log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-2000:]
        events = [l for l in recent if not _PRICE_TICK.match(l)]
        price_lines = [l for l in recent if _PRICE_TICK.match(l)]
        if price_lines:
            events.append("— " + price_lines[-1])
        return jsonify({"lines": events[-80:]})
    except Exception:
        return jsonify({"lines": []})


# ── Wallet balance endpoint ────────────────────────────────────────────────────
# Cached so the dashboard doesn't hammer the CLOB API on every 5s poll.
_balance_cache: dict = {"usdc": None, "fetched_at": 0.0}
_BALANCE_TTL = 30.0   # seconds between live refreshes


@app.route("/api/live/balance")
def api_live_balance():
    now = time.time()
    if now - _balance_cache["fetched_at"] < _BALANCE_TTL and _balance_cache["usdc"] is not None:
        return jsonify({"usdc": _balance_cache["usdc"]})
    try:
        import os
        from dotenv import load_dotenv
        load_dotenv()
        from src.bot.clob_auth import get_client
        from py_clob_client.clob_types import BalanceAllowanceParams, AssetType
        client = get_client()
        resp = client.get_balance_allowance(
            BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
        )
        # balance is returned in USDC micro-units (6 decimals)
        raw = float(resp.get("balance", 0))
        usdc = round(raw / 1_000_000, 2)
        _balance_cache["usdc"] = usdc
        _balance_cache["fetched_at"] = now
        return jsonify({"usdc": usdc})
    except Exception as e:
        return jsonify({"usdc": None, "error": str(e)})


# ── Patch version ─────────────────────────────────────────────────────────────

@app.route("/api/version")
def api_version():
    return jsonify({"patch": PATCH, "date": PATCH_DATE, "notes": PATCH_NOTES})


# ── Pause / resume controls ────────────────────────────────────────────────────

@app.route("/api/live/paused")
def api_live_paused():
    return jsonify({"paused": PAUSE_FLAG.exists()})


@app.route("/api/live/pause", methods=["POST"])
def api_live_pause():
    OUT_5M_LIVE.mkdir(parents=True, exist_ok=True)
    PAUSE_FLAG.touch()
    return jsonify({"paused": True})


@app.route("/api/live/resume", methods=["POST"])
def api_live_resume():
    PAUSE_FLAG.unlink(missing_ok=True)
    return jsonify({"paused": False})
