from __future__ import annotations

import csv
import json
import re
import time
from pathlib import Path

from flask import Flask, jsonify, render_template, request
from src.bot.version import PATCH, PATCH_DATE, PATCH_NOTES

# Module-level imports for the CLOB balance endpoint — previously imported on
# every /api/live/balance request (50-100ms cold start each time). Hoist them
# up so the cache-miss path is just the actual API call.
import os
from dotenv import load_dotenv
load_dotenv()
try:
    from src.bot.clob_auth import get_client as _get_clob_client
    from py_clob_client_v2 import BalanceAllowanceParams, AssetType
    _CLOB_IMPORTS_OK = True
except Exception as _e:
    _CLOB_IMPORTS_OK = False
    _CLOB_IMPORT_ERROR = str(_e)
import requests as _requests

# Price-tick lines: [HH:MM:SS] BTC UP=0.505 DOWN=0.495 | 179s left
_PRICE_TICK = re.compile(r"^\[\d{2}:\d{2}:\d{2}\] \w+ UP=")

OUT_5M       = Path(__file__).resolve().parents[2] / "output/5m_trading"
OUT_5M_LIVE  = Path(__file__).resolve().parents[2] / "output/5m_live"
OUT_ESPORTS  = Path(__file__).resolve().parents[2] / "output/esports_fade"
PAUSE_FLAG   = OUT_5M_LIVE / "paused.live.flag"

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
        raw = p.read_text(encoding="utf-8").strip()
        # Handle the historical invalid-JSON format {reset_at: VALUE} (unquoted key)
        # that was written before the file format was standardised.
        if raw.startswith("{reset_at:") or raw.startswith("{ reset_at:"):
            import re as _re
            m = _re.search(r"reset_at\s*:\s*(\d+)", raw)
            if m:
                return float(m.group(1))
        return float(json.loads(raw).get("reset_at", 0))
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
    # Compute all stats from trades.csv directly so this always matches the
    # equity graph (which also reads trades.csv). Previously read summary*.json
    # files which included stale files from disabled strategies (BTC-5m, momentum)
    # and an old untagged summary.json, causing the overview equity to diverge
    # from the equity graph.
    rows = _trades_since_reset()
    if not rows:
        return jsonify({})

    pnls      = [float(r["pnl_usd"]) for r in rows if r.get("pnl_usd")]
    win_pnls  = [p for p in pnls if p > 0]
    loss_pnls = [p for p in pnls if p <= 0]
    ct        = len(pnls)
    total_pnl = round(sum(pnls), 2)

    # open_positions: count rows in all positions CSVs (reflects live engine state)
    open_pos = 0
    for f in OUT_5M.glob("positions*.csv"):
        for r in _read_csv(f):
            if r.get("state", "").lower() == "open":
                open_pos += 1

    return jsonify({
        "equity":        total_pnl,
        "total_pnl":     total_pnl,
        "closed_trades": ct,
        "wins":          len(win_pnls),
        "losses":        len(loss_pnls),
        "win_rate":      round(len(win_pnls) / ct * 100, 1) if ct else 0.0,
        "avg_win":       round(sum(win_pnls)  / len(win_pnls),  2) if win_pnls  else 0.0,
        "avg_loss":      round(sum(loss_pnls) / len(loss_pnls), 2) if loss_pnls else 0.0,
        "open_positions": open_pos,
    })


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
    """
    LIVE summary now reads counts/PnL directly from trades_*.csv (single source
    of truth). Previously aggregated from summary*.json which the engine wrote
    based on in-memory state — but that missed manually-backfilled rows.

    open_positions still comes from summary*.json (engine knows its in-memory
    state).
    """
    totals = {"closed_trades": 0, "wins": 0, "losses": 0,
              "total_pnl": 0.0, "open_positions": 0}

    # Pull closed trades directly from CSVs
    all_rows = []
    for f in sorted(OUT_5M_LIVE.glob("trades*.csv")):
        all_rows.extend(_read_csv(f))
    closed = [r for r in all_rows if r.get("pnl_usd") not in (None, "")]
    totals["closed_trades"] = len(closed)
    win_pnls  = [float(r["pnl_usd"]) for r in closed if float(r["pnl_usd"]) > 0]
    loss_pnls = [float(r["pnl_usd"]) for r in closed if float(r["pnl_usd"]) <= 0]
    totals["wins"]   = len(win_pnls)
    totals["losses"] = len(loss_pnls)
    totals["total_pnl"] = round(sum(float(r["pnl_usd"]) for r in closed), 2)
    totals["avg_win"]   = round(sum(win_pnls)/len(win_pnls), 2)   if win_pnls   else 0.0
    totals["avg_loss"]  = round(sum(loss_pnls)/len(loss_pnls), 2) if loss_pnls  else 0.0

    # open_positions still from engine's summary.json (its in-memory truth)
    for f in OUT_5M_LIVE.glob("summary*.json"):
        d = _read_json(f)
        if d:
            totals["open_positions"] += int(d.get("open_positions", 0))

    if totals["closed_trades"] == 0 and totals["open_positions"] == 0:
        return jsonify({})

    ct = totals["closed_trades"]
    totals["win_rate"]  = round(totals["wins"] / ct * 100, 1) if ct else 0.0
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
    clean.sort(key=lambda r: float(r.get("opened_at") or 0))
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
_BALANCE_TTL = 12.0   # seconds between live refreshes (was 30s — kept lagging during trades)


@app.route("/api/live/balance")
def api_live_balance():
    now = time.time()
    if now - _balance_cache["fetched_at"] < _BALANCE_TTL and _balance_cache["usdc"] is not None:
        return jsonify({"usdc": _balance_cache["usdc"]})
    if not _CLOB_IMPORTS_OK:
        return jsonify({"usdc": None, "error": f"CLOB import failed: {_CLOB_IMPORT_ERROR}"})
    try:
        client = _get_clob_client()
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


@app.route("/api/live/risk")
def api_live_risk():
    """
    LIVE risk-state summary: daily loss vs cap, position size, headroom.
    Reads .env for the user-configured caps and trades.csv for today's PnL.
    """
    import datetime as _dt
    now = time.time()
    today_start = _dt.datetime.now(_dt.timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    ).timestamp()

    today_pnl = 0.0
    today_n = 0
    for asset in ("BTC", "ETH", "SOL"):
        for r in _read_csv(OUT_5M_LIVE / f"trades_{asset}-15m.csv"):
            try:
                if float(r.get("closed_at") or 0) >= today_start:
                    today_pnl += float(r.get("pnl_usd") or 0)
                    today_n += 1
            except (TypeError, ValueError):
                pass

    daily_loss_cap = float(os.environ.get("LIVE_MAX_DAILY_LOSS_USD", "50"))
    position_size  = float(os.environ.get("LIVE_POSITION_SIZE_USD", "5"))
    headroom = round(daily_loss_cap + today_pnl, 2)  # cap is positive number; today_pnl is signed
    return jsonify({
        "daily_loss_cap_usd": daily_loss_cap,
        "position_size_usd":  position_size,
        "today_pnl":          round(today_pnl, 2),
        "today_trades":       today_n,
        "headroom_to_cap":    headroom,
        "near_cap":           headroom < 10.0,   # warn when within $10 of breaker
    })


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


# ── v1.34: LIVE readiness, brain advice, health ───────────────────────────────

# Entry-band thresholds per (asset, window). Must mirror market_5m.py constants.
_ENTRY_BANDS = {
    ("BTC", "15m"): {"min": 0.38, "max": 0.40, "live": False},
    ("ETH", "15m"): {"min": 0.35, "max": 0.40, "live": True},   # v1.34: LIVE re-enabled (gated)
    ("SOL", "15m"): {"min": 0.33, "max": 0.35, "live": True},
    ("BTC", "4h"):  {"min": 0.28, "max": 0.45, "live": False},  # PAPER experiment
    ("ETH", "4h"):  {"min": 0.28, "max": 0.45, "live": False},
    ("SOL", "4h"):  {"min": 0.28, "max": 0.45, "live": False},
}


def _recent_wr(asset: str, window: str, n: int = 8):
    """Return (wins, total) over last N closed MR trades for the asset+window."""
    rows = _read_csv(OUT_5M / "trades.csv")
    rows = [r for r in rows
            if r.get("asset", "").upper() == asset.upper()
            and r.get("window") == window
            and r.get("strategy") == "mean_reversion"
            and r.get("exit_reason") not in ("", "open")]
    recent = rows[-n:]
    if len(recent) < n:
        return 0, len(recent)
    wins = sum(1 for r in recent if (float(r.get("pnl_usd") or 0) > 0))
    return wins, len(recent)


@app.route("/api/live/readiness")
def api_live_readiness():
    """
    Per (asset, window) LIVE entry-readiness snapshot.

    For each LIVE-eligible market, lists the gates and which currently pass.
    A market is `ready_to_trade=True` only if all gates pass.

    Frontend uses this to display: "ETH LIVE: blocked (recent 4/8 WR < 5/8)"
    """
    paused = PAUSE_FLAG.exists()
    out = {"live_paused": paused, "assets": {}}

    for (asset, window), band in _ENTRY_BANDS.items():
        if not band["live"]:
            continue   # PAPER-only segment
        key = f"{asset}-{window}"
        gates = []
        # Pause flag gate
        gates.append({
            "name": "live_pause_flag",
            "passed": not paused,
            "detail": "flag present" if paused else "active",
        })
        # WR filter (currently only enforced for ETH-15m on LIVE)
        if asset == "ETH" and window == "15m":
            wins, total = _recent_wr(asset, window, n=8)
            wr_ok = (total >= 8) and (wins >= 5)
            if total < 8:
                detail = f"only {total} recent trades (need 8)"
            else:
                detail = f"{wins}/{total} wins {'>=' if wr_ok else '<'} 5/8 threshold"
            gates.append({
                "name": "wr_filter_5_of_8",
                "passed": wr_ok,
                "detail": detail,
                "wins": wins,
                "total": total,
            })
        all_pass = all(g["passed"] for g in gates)
        out["assets"][key] = {
            "live_eligible": True,
            "entry_band_min": band["min"],
            "entry_band_max": band["max"],
            "gates": gates,
            "ready_to_trade": all_pass,
        }

    return jsonify(out)


# Cached brain advice scrape — bot.log is huge so we tail-and-cache.
_BRAIN_LINE_RE = re.compile(
    r"\[BRAIN\]\s+(?P<asset>[A-Z]{3})\s+regime=(?P<regime>\w+)\s+"
    r"mr_edge=(?P<mr_edge>\w+)\s+modifier=(?P<mod>[+\-][0-9.]+).*?[—-]\s*(?P<reasoning>.+)$"
)


@app.route("/api/brain")
def api_brain():
    """
    Returns the most recent N brain advice rows.
    v1.34: prefers brain_decisions.csv (structured); falls back to bot.log
    parsing if the CSV doesn't exist yet.
    """
    csv_path = OUT_5M / "brain_decisions.csv"
    if csv_path.exists():
        try:
            rows = _read_csv(csv_path)[-8:]
            advice = []
            for r in rows:
                try:
                    advice.append({
                        "asset":     r.get("asset", "?"),
                        "window":    r.get("window", ""),
                        "regime":    r.get("regime", ""),
                        "mr_edge":   r.get("mr_edge", ""),
                        "modifier":  float(r.get("modifier") or 0),
                        "reasoning": (r.get("reasoning") or "")[:200],
                        "timestamp": float(r.get("timestamp") or 0),
                    })
                except (TypeError, ValueError):
                    continue
            return jsonify({"advice": advice, "source": "csv"})
        except Exception as exc:
            return jsonify({"advice": [], "source": "csv", "error": str(exc)[:120]})

    # Fallback: parse bot.log
    log_path = Path(__file__).resolve().parents[2] / "bot.log"
    if not log_path.exists():
        return jsonify({"advice": [], "source": "none"})
    try:
        max_bytes = 300 * 1024
        size = log_path.stat().st_size
        with log_path.open("rb") as fh:
            if size > max_bytes:
                fh.seek(size - max_bytes)
            chunk = fh.read().decode("utf-8", errors="replace")
        lines = chunk.splitlines()
        advice = []
        for line in lines:
            m = _BRAIN_LINE_RE.search(line)
            if m:
                advice.append({
                    "asset": m.group("asset"),
                    "regime": m.group("regime"),
                    "mr_edge": m.group("mr_edge"),
                    "modifier": float(m.group("mod")),
                    "reasoning": m.group("reasoning").strip()[:200],
                })
        return jsonify({"advice": advice[-8:], "source": "log"})
    except Exception as exc:
        return jsonify({"advice": [], "source": "log", "error": str(exc)[:120]})


@app.route("/api/decisions")
def api_decisions():
    """
    Aggregates the last N hours of skipped_windows.csv so the user can see
    WHY the bot is/isn't trading right now.

    Query params:
      hours: lookback window (default 24)

    Response:
      {
        "hours": 24,
        "total_skipped": 1234,
        "by_reason": {"price_too_high": 600, "btc_filter": 300, ...},
        "by_asset": {"BTC": {"total": 400, "by_reason": {...}}, ...},
        "trades_entered_in_window": 8
      }
    """
    try:
        hours = int(request.args.get("hours", 24))
    except (TypeError, ValueError):
        hours = 24
    cutoff_ts = time.time() - (hours * 3600)

    skipped_rows = _read_csv(OUT_5M / "skipped_windows.csv")
    recent_skips = [r for r in skipped_rows
                    if float(r.get("window_end_ts") or 0) >= cutoff_ts]

    by_reason = {}
    by_asset = {}
    for r in recent_skips:
        reason = r.get("skip_reason", "?")
        asset = (r.get("asset") or "?").upper()
        by_reason[reason] = by_reason.get(reason, 0) + 1
        ab = by_asset.setdefault(asset, {"total": 0, "by_reason": {}})
        ab["total"] += 1
        ab["by_reason"][reason] = ab["by_reason"].get(reason, 0) + 1

    # Sort reasons by count
    by_reason = dict(sorted(by_reason.items(), key=lambda kv: -kv[1]))
    for ab in by_asset.values():
        ab["by_reason"] = dict(sorted(ab["by_reason"].items(), key=lambda kv: -kv[1]))

    trades_rows = _read_csv(OUT_5M / "trades.csv")
    entered = sum(1 for r in trades_rows if float(r.get("opened_at") or 0) >= cutoff_ts)

    return jsonify({
        "hours":                    hours,
        "total_skipped":            len(recent_skips),
        "trades_entered_in_window": entered,
        "by_reason":                by_reason,
        "by_asset":                 by_asset,
    })


@app.route("/api/orphans")
def api_orphans():
    """
    Returns count of Polymarket positions held by our wallet that the bot
    doesn't have a trade row for — i.e. positions opened but never closed
    in our records. The 4-hour ReconcileBackfill task should keep this at 0.
    If it climbs > 0, the backfill is failing or new orphans are appearing
    faster than the task can catch them.

    Cached 60s (Polymarket /positions is fine to hit but not on every poll).
    """
    cache = api_orphans._cache  # type: ignore[attr-defined]
    now = time.time()
    if now - cache["ts"] < 60:
        return jsonify(cache["data"])

    address = os.environ.get("POLYMARKET_PROXY_ADDRESS", "").strip()
    if not address:
        return jsonify({"error": "no proxy address"})

    try:
        r = _requests.get(
            "https://data-api.polymarket.com/positions",
            params={"user": address, "limit": 200},
            timeout=8,
        )
        positions = r.json() if r.status_code == 200 else []
    except Exception as e:
        return jsonify({"error": str(e)[:80]})

    # Local conditions
    local_conds = set()
    for asset in ("BTC", "ETH", "SOL"):
        for row in _read_csv(OUT_5M_LIVE / f"trades_{asset}-15m.csv"):
            cid = row.get("condition_id", "")
            if cid:
                local_conds.add(cid)

    orphans = []
    for p in positions:
        cid = p.get("conditionId") or p.get("condition_id") or ""
        if not cid or cid in local_conds:
            continue
        orphans.append({
            "condition_id": cid,
            "slug":         p.get("slug", ""),
            "shares":       p.get("size", 0),
            "redeemable":   p.get("redeemable", False),
            "avg_price":    p.get("avgPrice", 0),
        })
    data = {
        "n_orphans":    len(orphans),
        "n_positions":  len(positions),
        "orphans":      orphans[:10],   # first 10 for display
        "checked_at":   now,
    }
    cache["ts"] = now
    cache["data"] = data
    return jsonify(data)
api_orphans._cache = {"ts": 0.0, "data": {}}


@app.route("/api/healthz")
def api_healthz():
    """
    Strict monitoring endpoint. Returns:
      200  if everything is alive and recent (suitable for uptime monitoring)
      503  if any critical signal is stale; body lists which checks failed

    Designed for external pings (e.g. uptimerobot.com hitting this endpoint
    every 5 minutes — alert on 503).

    Checks:
      - skipped_windows.csv written in last 5 minutes  (PAPER is evaluating)
      - bot.log written in last 60 seconds            (any process is alive)
      - Optional: paused.live.flag NOT present       (skipped — pause is intentional)
    """
    now = time.time()
    root = Path(__file__).resolve().parents[2]

    failures = []
    checks = {}

    skipped = OUT_5M / "skipped_windows.csv"
    if skipped.exists():
        age = now - skipped.stat().st_mtime
        checks["skipped_windows_age_sec"] = round(age, 1)
        if age > 300:
            failures.append(f"skipped_windows.csv stale ({int(age)}s > 300s)")
    else:
        failures.append("skipped_windows.csv missing")
        checks["skipped_windows_age_sec"] = None

    bot_log = root / "bot.log"
    if bot_log.exists():
        age = now - bot_log.stat().st_mtime
        checks["bot_log_age_sec"] = round(age, 1)
        if age > 60:
            failures.append(f"bot.log stale ({int(age)}s > 60s)")
    else:
        failures.append("bot.log missing")
        checks["bot_log_age_sec"] = None

    # Trades-csv recency: if 24h+ since last write AND LIVE is unpaused, may be a problem
    # but it's normal during quiet markets — don't fail healthz on this.
    trades = OUT_5M / "trades.csv"
    if trades.exists():
        checks["paper_trades_age_sec"] = round(now - trades.stat().st_mtime, 1)

    status = "ok" if not failures else "fail"
    resp = jsonify({
        "status":   status,
        "checks":   checks,
        "failures": failures,
        "version":  PATCH,
    })
    resp.status_code = 200 if not failures else 503
    return resp


@app.route("/api/health")
def api_health():
    """
    Bot health summary for the dashboard.
    NOT a monitoring endpoint - just descriptive snapshots.
    """
    now = time.time()
    root = Path(__file__).resolve().parents[2]

    def _age_secs(p):
        try:
            return now - p.stat().st_mtime
        except Exception:
            return None

    skipped  = OUT_5M / "skipped_windows.csv"
    trades   = OUT_5M / "trades.csv"
    bot_log  = root / "bot.log"
    watchdog = root / "watchdog_paper.log"

    return jsonify({
        "skipped_windows_age_sec": _age_secs(skipped),
        "paper_trades_age_sec":    _age_secs(trades),
        "bot_log_age_sec":         _age_secs(bot_log),
        "bot_log_size_mb":         (bot_log.stat().st_size / (1024*1024)) if bot_log.exists() else 0,
        "watchdog_paper_age_sec":  _age_secs(watchdog),
        "version":                 PATCH,
        "version_date":            PATCH_DATE,
    })


# ══════════════════════════════════════════════════════════════════════════════
# ESPORTS FADE BOT  —  fully independent CS2 fade-trading bot.
# Separate process (PolyBotEsports), separate output dir, separate strategy.
# Do NOT mix with the 15m Up/Down crypto endpoints above.
# ══════════════════════════════════════════════════════════════════════════════

ES_TRADES_CSV   = OUT_ESPORTS / "paper_trades.csv"
ES_RESULTS_CSV  = OUT_ESPORTS / "paper_results.csv"
ES_BOT_LOG      = OUT_ESPORTS / "bot.log"
ES_WATCHDOG_LOG = Path(__file__).resolve().parents[2] / "watchdog_esports.log"
ES_LIVE_ORDERS_JSONL = OUT_ESPORTS / "live_orders.jsonl"
ES_LIVE_RESULTS_CSV  = OUT_ESPORTS / "live_results.csv"
ES_LIVE_DAILY_PNL    = OUT_ESPORTS / "live_daily_pnl.json"
ES_MARKET_TIMES      = OUT_ESPORTS / "market_times.json"


def _load_market_times_cache() -> dict[str, dict]:
    if not ES_MARKET_TIMES.exists():
        return {}
    try:
        return json.loads(ES_MARKET_TIMES.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_market_times_cache(cache: dict[str, dict]):
    try:
        import os as _os
        tmp = ES_MARKET_TIMES.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(cache, indent=2), encoding="utf-8")
        _os.replace(tmp, ES_MARKET_TIMES)
    except Exception:
        pass


_MARKET_TIMES_MEM: dict[str, dict] = {}
_MARKET_TIMES_LOADED = False


def _get_market_meta(condition_id: str) -> dict | None:
    """Return cached market metadata for a conditionId, fetching on cache miss.

    Fields:
      - game_start_time : ISO time the match starts
      - end_date_iso    : market resolution deadline
      - question        : human-readable market question (e.g.,
        "Counter-Strike: Natus Vincere vs Vitality - Map 1 Winner")

    Cache persisted to ES_MARKET_TIMES.
    """
    global _MARKET_TIMES_MEM, _MARKET_TIMES_LOADED
    if not _MARKET_TIMES_LOADED:
        _MARKET_TIMES_MEM = _load_market_times_cache()
        _MARKET_TIMES_LOADED = True
    if not condition_id:
        return None
    cached = _MARKET_TIMES_MEM.get(condition_id)
    # Backfill question for entries that were cached before this field was added.
    if cached and "question" in cached:
        return cached
    try:
        r = _requests.get(f"https://clob.polymarket.com/markets/{condition_id}", timeout=4)
        if r.status_code != 200:
            return cached  # keep stale cache rather than wiping
        j = r.json()
        info = {
            "game_start_time": j.get("game_start_time") or "",
            "end_date_iso":    j.get("end_date_iso") or "",
            "question":        j.get("question") or "",
        }
        _MARKET_TIMES_MEM[condition_id] = info
        _save_market_times_cache(_MARKET_TIMES_MEM)
        return info
    except Exception:
        return cached


# Back-compat alias for older callers
_get_market_times = _get_market_meta


def _es_signal_rows() -> list[dict]:
    if not ES_TRADES_CSV.exists():
        return []
    rows = []
    with open(ES_TRADES_CSV, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            r = {k: v for k, v in r.items() if k is not None}
            rows.append(r)
    return rows


@app.route("/api/esports/summary")
def api_esports_summary():
    """Aggregate stats: signals logged, last signal age, realized PnL (if eval ran)."""
    rows = _es_signal_rows()
    now = time.time()
    last_signal_ts = 0.0
    if rows:
        try:
            last_signal_ts = float(rows[-1].get("timestamp") or 0)
        except (TypeError, ValueError):
            last_signal_ts = 0.0
    # Count today's signals (UTC day)
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).date()
    signals_today = 0
    for r in rows:
        try:
            ts = float(r.get("timestamp") or 0)
            if datetime.fromtimestamp(ts, tz=timezone.utc).date() == today:
                signals_today += 1
        except (TypeError, ValueError):
            continue

    # Realized PnL — only available after running analysis/evaluate_paper.py
    results = []
    if ES_RESULTS_CSV.exists():
        with open(ES_RESULTS_CSV, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                r = {k: v for k, v in r.items() if k is not None}
                results.append(r)

    n_resolved = sum(1 for r in results if r.get("status") in ("WIN", "LOSS"))
    n_wins     = sum(1 for r in results if r.get("status") == "WIN")
    total_pnl  = 0.0
    total_bet  = 0.0
    for r in results:
        if r.get("status") not in ("WIN", "LOSS"):
            continue
        try:
            total_pnl += float(r.get("realized_pnl") or 0)
            total_bet += float(r.get("our_bet") or 0)
        except (TypeError, ValueError):
            continue

    fade_count = 0
    follow_count = 0
    try:
        es_dir = Path(__file__).resolve().parents[2] / "cowork_snapshot" / "esports"
        fade_path = es_dir / "fade_targets.json"
        if fade_path.exists():
            fade_count = len(json.loads(fade_path.read_text(encoding="utf-8")).get("target_wallets") or [])
        follow_path = es_dir / "follow_targets.json"
        if follow_path.exists():
            follow_count = len(json.loads(follow_path.read_text(encoding="utf-8")).get("target_wallets") or [])
    except Exception:
        pass

    # Per-strategy signal counts
    fade_total = sum(1 for r in rows if (r.get("strategy") or "fade") == "fade")
    follow_total = sum(1 for r in rows if r.get("strategy") == "follow")

    return jsonify({
        "mode":                "PAPER",  # bot is currently always paper from dashboard's POV
        "target_wallet_count": fade_count + follow_count,
        "fade_wallet_count":   fade_count,
        "follow_wallet_count": follow_count,
        "fade_signals_total":  fade_total,
        "follow_signals_total":follow_total,
        "signals_total":       len(rows),
        "signals_today_utc":   signals_today,
        "last_signal_age_sec": (now - last_signal_ts) if last_signal_ts else None,
        # Realized — only populated when analysis/evaluate_paper.py has been run
        "resolved":            n_resolved,
        "wins":                n_wins,
        "win_rate_pct":        round((n_wins / n_resolved * 100), 2) if n_resolved else None,
        "total_pnl_usd":       round(total_pnl, 2),
        "total_bet_usd":       round(total_bet, 2),
        "roi_pct":             round((total_pnl / total_bet * 100), 2) if total_bet else None,
        "results_age_sec":     (now - ES_RESULTS_CSV.stat().st_mtime) if ES_RESULTS_CSV.exists() else None,
    })


@app.route("/api/esports/recent")
def api_esports_recent():
    """Last N signals, newest first, with realized PnL/status when available.

    Prefers paper_results.csv (has status + realized_pnl). Falls back to
    paper_trades.csv if results haven't been computed yet.
    """
    try:
        n = int(request.args.get("n", "25"))
    except ValueError:
        n = 25

    # Prefer the results CSV — it has every row from paper_trades.csv plus
    # status (WIN/LOSS/UNRESOLVED) and realized_pnl.
    if ES_RESULTS_CSV.exists():
        rows = []
        with open(ES_RESULTS_CSV, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                rows.append({k: v for k, v in r.items() if k is not None})
    else:
        rows = _es_signal_rows()

    # The signal CSV is append-only chronologically; tail then reverse for newest-first.
    rows = rows[-n:]
    rows.reverse()

    # Enrich with game start/end times + question from per-conditionId cache.
    # On cache miss we fetch CLOB once and persist — subsequent calls are free.
    for r in rows:
        cid = r.get("fade_condition")
        if not cid:
            continue
        info = _get_market_meta(cid)
        if info:
            r["game_start_time"] = info.get("game_start_time") or ""
            r["end_date_iso"]    = info.get("end_date_iso") or ""
            r["question"]        = info.get("question") or ""

    return jsonify(rows)


# ── Orderbook bid cache (30s TTL) — many positions can be priced in one render
_bid_cache: dict[str, tuple[float, float]] = {}   # token_id -> (best_bid, fetched_at)
_BID_TTL = 30.0
_clob_client_for_bids = None


def _get_best_bid(token_id: str) -> float | None:
    """Cached best-bid lookup for a token_id. Returns None on error."""
    global _clob_client_for_bids
    if not token_id:
        return None
    now = time.time()
    cached = _bid_cache.get(token_id)
    if cached and (now - cached[1]) < _BID_TTL:
        return cached[0]
    if _clob_client_for_bids is None:
        try:
            if not _CLOB_IMPORTS_OK:
                return None
            _clob_client_for_bids = _get_clob_client()
        except Exception:
            return None
    try:
        ob = _clob_client_for_bids.get_order_book(str(token_id)) or {}
        bids = ob.get("bids") if isinstance(ob, dict) else []
        if not bids:
            best = 0.0
        else:
            last = bids[-1]
            best = float(last.get("price") if isinstance(last, dict) else 0)
        _bid_cache[token_id] = (best, now)
        return best
    except Exception:
        # On error, return stale cache if we have it, else None
        return cached[0] if cached else None


@app.route("/api/esports/live/open")
def api_esports_live_open():
    """Currently-open LIVE positions, aggregated per (token_id) with live best
    bid + unrealized PnL. The dashboard's 'Open Positions' table reads this.

    A position is OPEN when:
      - it has at least one matched BUY
      - the cumulative SELLs are < cumulative BUYs (some shares still owned)
      - the market hasn't resolved (no winner yet)
    """
    orders = []
    if ES_LIVE_ORDERS_JSONL.exists():
        with open(ES_LIVE_ORDERS_JSONL, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    orders.append(json.loads(line))
                except Exception:
                    continue

    # Aggregate matched orders per token_id
    from collections import defaultdict
    pos = defaultdict(lambda: {
        "buy_shares": 0.0, "buy_cost": 0.0, "buy_count": 0,
        "sell_shares": 0.0, "sell_proceeds": 0.0,
        "first_ts": None, "last_ts": None,
        "slug": "", "outcome": "", "strategy": "", "condition_id": "", "target_wallet": "",
    })
    for o in orders:
        if str(o.get("status", "")).lower() != "matched":
            continue
        tid = str(o.get("token_id") or "")
        if not tid:
            continue
        p = pos[tid]
        side = str(o.get("side", "BUY")).upper()
        shares = float(o.get("shares") or 0)
        cost   = float(o.get("cost_usd") or 0)
        ts     = float(o.get("ts") or 0)
        if side == "BUY":
            p["buy_shares"] += shares
            p["buy_cost"]   += cost
            p["buy_count"]  += 1
            if not p["slug"]:
                p["slug"]         = o.get("fade_slug", "")
                p["outcome"]      = o.get("our_outcome", "")
                p["strategy"]     = o.get("strategy", "fade")
                p["condition_id"] = o.get("fade_condition", "")
                p["target_wallet"] = o.get("target_wallet", "")
            if p["first_ts"] is None or ts < p["first_ts"]:
                p["first_ts"] = ts
            if p["last_ts"] is None or ts > p["last_ts"]:
                p["last_ts"] = ts
        else:  # SELL
            p["sell_shares"]   += shares
            p["sell_proceeds"] += cost

    # Filter to actually-open (have unsold shares + market not resolved)
    open_rows = []
    now = time.time()
    for tid, p in pos.items():
        unsold = p["buy_shares"] - p["sell_shares"]
        if unsold < 0.01 or p["buy_shares"] < 0.01:
            continue
        # Check market resolution
        meta = _get_market_meta(p["condition_id"]) if p["condition_id"] else None
        end_iso = (meta or {}).get("end_date_iso", "")
        game_start = (meta or {}).get("game_start_time", "")
        question   = (meta or {}).get("question", "")

        # Current best bid for our outcome — drives unrealized PnL
        best_bid = _get_best_bid(tid)
        unrealized = None
        if best_bid is not None:
            current_value = unsold * best_bid
            # Already-collected proceeds offset what we paid
            unrealized = current_value + p["sell_proceeds"] - p["buy_cost"]

        avg_cost = (p["buy_cost"] / p["buy_shares"]) if p["buy_shares"] else 0
        held_for = (now - p["first_ts"]) if p["first_ts"] else 0

        open_rows.append({
            "token_id":       tid,
            "condition_id":   p["condition_id"],
            "fade_slug":      p["slug"],
            "question":       question,
            "our_outcome":    p["outcome"],
            "strategy":       p["strategy"],
            "target_wallet":  p["target_wallet"],
            "buy_count":      p["buy_count"],
            "shares_owned":   round(unsold, 4),
            "avg_cost":       round(avg_cost, 4),
            "total_cost":     round(p["buy_cost"], 2),
            "sold_shares":    round(p["sell_shares"], 4),
            "sold_proceeds":  round(p["sell_proceeds"], 2),
            "current_bid":    round(best_bid, 4) if best_bid is not None else None,
            "unrealized_pnl": round(unrealized, 2) if unrealized is not None else None,
            "first_buy_ts":   p["first_ts"],
            "held_seconds":   round(held_for),
            "game_start_time": game_start,
            "end_date_iso":   end_iso,
        })

    # Sort: highest current value first (most exposure)
    open_rows.sort(key=lambda r: r["total_cost"], reverse=True)

    total_cost   = sum(r["total_cost"] for r in open_rows)
    total_value  = sum((r["shares_owned"] * (r["current_bid"] or 0)) for r in open_rows)
    total_unreal = sum((r["unrealized_pnl"] or 0) for r in open_rows)

    return jsonify({
        "open_positions":         open_rows,
        "summary": {
            "n_positions":        len(open_rows),
            "total_cost_usd":     round(total_cost, 2),
            "current_value_usd":  round(total_value, 2),
            "unrealized_pnl_usd": round(total_unreal, 2),
        },
    })


@app.route("/api/esports/live")
def api_esports_live():
    """LIVE bot order snapshot: total orders, fills, today's PnL, recent orders.

    Returns empty/zero values if the bot has never run in LIVE mode (no
    live_orders.jsonl yet).
    """
    orders = []
    if ES_LIVE_ORDERS_JSONL.exists():
        with open(ES_LIVE_ORDERS_JSONL, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    orders.append(json.loads(line))
                except Exception:
                    continue

    # BUYs cost us $; SELLs return $. Old rows pre-side-tag are assumed BUY.
    def _is_buy(o):  return str(o.get("side", "BUY")).upper() == "BUY"
    def _is_sell(o): return str(o.get("side", "BUY")).upper() == "SELL"

    n_total     = sum(1 for o in orders if _is_buy(o))
    n_filled    = sum(1 for o in orders if _is_buy(o) and str(o.get("status","")).lower() == "matched")
    n_cancelled = sum(1 for o in orders if _is_buy(o) and str(o.get("status","")).lower() in ("cancelled","canceled"))
    total_cost  = sum(float(o.get("cost_usd") or 0) for o in orders if _is_buy(o))
    n_sells     = sum(1 for o in orders if _is_sell(o))
    total_proceeds = sum(float(o.get("cost_usd") or 0) for o in orders if _is_sell(o))

    daily = {}
    if ES_LIVE_DAILY_PNL.exists():
        try:
            daily = json.loads(ES_LIVE_DAILY_PNL.read_text(encoding="utf-8"))
        except Exception:
            daily = {}

    # Recent CLOSED (resolved + cancelled) orders only — open positions live in
    # the dedicated /api/esports/live/open endpoint now.
    recent = []
    if ES_LIVE_RESULTS_CSV.exists():
        with open(ES_LIVE_RESULTS_CSV, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                row = {k: v for k, v in r.items() if k is not None}
                # Skip currently-open positions (they're in the OPEN endpoint)
                if row.get("status") in ("UNRESOLVED", "open"):
                    continue
                # Skip SELLs (folded into BUY pairing in evaluator)
                if str(row.get("side", "BUY")).upper() == "SELL":
                    continue
                recent.append(row)
        recent = recent[-25:][::-1]
    else:
        recent = [o for o in orders if str(o.get("side", "BUY")).upper() != "SELL"][-25:][::-1]

    # Enrich each recent live order with the market question (for "Vitality wins
    # Map 1"-style displays) and resolution deadline.
    for r in recent:
        cid = r.get("fade_condition") or r.get("conditionId")
        if not cid:
            continue
        info = _get_market_meta(cid)
        if info:
            r["question"]        = info.get("question") or ""
            r["game_start_time"] = info.get("game_start_time") or ""
            r["end_date_iso"]    = info.get("end_date_iso") or ""

    return jsonify({
        "orders_total":      n_total,
        "orders_filled":     n_filled,
        "orders_cancelled":  n_cancelled,
        "total_cost_usd":    round(total_cost, 2),
        "early_sells":       n_sells,
        "early_proceeds_usd": round(total_proceeds, 2),
        "daily":             daily,
        "recent":            recent,
    })


@app.route("/api/esports/status")
def api_esports_status():
    """Bot process liveness via log file freshness."""
    now = time.time()

    def _age(p: Path):
        try:
            return now - p.stat().st_mtime
        except Exception:
            return None

    log_tail = ""
    if ES_BOT_LOG.exists():
        try:
            with open(ES_BOT_LOG, encoding="utf-8", errors="replace") as f:
                lines = f.readlines()[-15:]
                log_tail = "".join(lines)
        except Exception:
            log_tail = ""

    return jsonify({
        "bot_log_age_sec":      _age(ES_BOT_LOG),
        "watchdog_log_age_sec": _age(ES_WATCHDOG_LOG),
        "trades_csv_age_sec":   _age(ES_TRADES_CSV),
        "log_tail":             log_tail,
    })
