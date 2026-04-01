from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd
from flask import Flask, jsonify, render_template

OUTPUT_DIR = Path(__file__).resolve().parents[2] / "output/paper_trading/polymarket"

app = Flask(__name__)

_bot_process: subprocess.Popen | None = None


def _read_json(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text())
    return {}


def _read_csv(path: Path) -> list[dict]:
    if path.exists():
        df = pd.read_csv(path)
        return df.where(pd.notna(df), None).to_dict("records")
    return []


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/summary")
def summary():
    return jsonify(_read_json(OUTPUT_DIR / "summary.json"))


@app.route("/api/positions")
def positions():
    rows = _read_csv(OUTPUT_DIR / "positions.csv")
    keep = ["question", "outcome", "entry_price", "current_price", "size", "unrealized_pnl", "opened_at"]
    import os, datetime as dt
    max_hold = int(os.getenv("PAPER_MAX_HOLDING_SECONDS", 28800))
    result = []
    for r in rows:
        row = {k: r.get(k) for k in keep}
        try:
            opened = dt.datetime.fromisoformat(str(r["opened_at"]).replace("Z", "+00:00"))
            row["force_close_at"] = (opened + dt.timedelta(seconds=max_hold)).isoformat()
        except Exception:
            row["force_close_at"] = None
        result.append(row)
    return jsonify(result)


@app.route("/api/closed_trades")
def closed_trades():
    rows = _read_csv(OUTPUT_DIR / "closed_trades.csv")
    keep = ["question", "outcome", "entry_price", "exit_price", "realized_pnl", "exit_reason", "holding_seconds"]
    return jsonify([{k: r.get(k) for k in keep} for r in rows])


@app.route("/api/equity_history")
def equity_history():
    ledger_path = OUTPUT_DIR / "ledger.csv"
    if not ledger_path.exists():
        return jsonify([])
    df = pd.read_csv(ledger_path)
    if "run_at" not in df.columns or "equity_after" not in df.columns:
        return jsonify([])
    df = df.dropna(subset=["run_at", "equity_after"])
    df["run_at"] = pd.to_datetime(df["run_at"], utc=True, errors="coerce")
    df = df.sort_values("run_at")
    return jsonify([
        {"time": str(row["run_at"]), "equity": round(float(row["equity_after"]), 2)}
        for _, row in df.iterrows()
    ])


@app.route("/api/signals")
def signals():
    rows = _read_csv(OUTPUT_DIR / "signals.csv")
    keep = ["question", "outcome", "market_price", "edge", "price_momentum", "conviction", "signal", "entry_reason"]
    result = [{k: r.get(k) for k in keep} for r in rows]
    # Sort: buy signals first, then by conviction descending
    result.sort(key=lambda r: (0 if r.get("signal") == "buy" else 1, -(r.get("conviction") or 0)))
    return jsonify(result[:20])


@app.route("/api/debug")
def debug():
    """Diagnostic endpoint: raw stats from signals.csv and data snapshot files."""
    import math
    import os

    project_root = Path(__file__).resolve().parents[2]
    result = {}

    # signals.csv stats
    signals_path = OUTPUT_DIR / "signals.csv"
    if signals_path.exists():
        rows = _read_csv(signals_path)
        edges = [r.get("edge") for r in rows if r.get("edge") is not None]
        momentum = [r.get("price_momentum") for r in rows if r.get("price_momentum") is not None]
        trade_counts = [r.get("recent_trade_count") for r in rows if r.get("recent_trade_count") is not None]
        staleness = [r.get("seconds_since_last_trade") for r in rows if r.get("seconds_since_last_trade") is not None]
        result["signals_csv"] = {
            "total_rows": len(rows),
            "buy_count": sum(1 for r in rows if r.get("signal") == "buy"),
            "edge_max": max(edges) if edges else None,
            "edge_min": min(edges) if edges else None,
            "momentum_max": max(momentum) if momentum else None,
            "momentum_min": min(momentum) if momentum else None,
            "recent_trade_count_max": max(trade_counts) if trade_counts else None,
            "recent_trade_count_zero_pct": sum(1 for t in trade_counts if t == 0) / len(trade_counts) if trade_counts else None,
            "staleness_min_s": min(staleness) if staleness else None,
            "staleness_max_s": max(staleness) if staleness else None,
            "file_mtime": os.path.getmtime(signals_path),
        }
    else:
        result["signals_csv"] = "missing"

    # parquet snapshot stats
    for name, path in [
        ("polymarket_markets", project_root / "data/current/polymarket/markets.parquet"),
        ("polymarket_trades", project_root / "data/current/polymarket/trades.parquet"),
        ("kalshi_markets", project_root / "data/current/kalshi/markets.parquet"),
        ("kalshi_trades", project_root / "data/current/kalshi/trades.parquet"),
    ]:
        if path.exists():
            try:
                df = pd.read_parquet(path)
                info = {"rows": len(df), "columns": list(df.columns), "file_mtime": os.path.getmtime(path)}
                if "timestamp" in df.columns:
                    ts = pd.to_numeric(df["timestamp"], errors="coerce").dropna()
                    if not ts.empty:
                        info["timestamp_min"] = int(ts.min())
                        info["timestamp_max"] = int(ts.max())
                result[name] = info
            except Exception as e:
                result[name] = {"error": str(e)}
        else:
            result[name] = "missing"

    return jsonify(result)


@app.route("/api/performance")
def performance():
    return jsonify(_read_json(OUTPUT_DIR / "performance_breakdown.json"))


@app.route("/api/bot/log")
def bot_log():
    log_path = Path(__file__).resolve().parents[2] / "bot.log"
    if not log_path.exists():
        return jsonify({"lines": []})
    with open(log_path) as f:
        lines = f.readlines()
    return jsonify({"lines": [l.rstrip() for l in lines[-50:]]})


@app.route("/api/bot/status")
def bot_status():
    global _bot_process
    # First check our own subprocess handle.
    if _bot_process is not None and _bot_process.poll() is None:
        return jsonify({"running": True})
    # Also detect bots started outside the dashboard (e.g. from terminal).
    import subprocess as _sp
    try:
        result = _sp.run(
            ["tasklist", "/FI", "IMAGENAME eq python.exe", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=3
        )
        # Check if any python process has paper-loop in its command line
        wmic = _sp.run(
            ["wmic", "process", "where", "name='python.exe'", "get", "commandline", "/format:list"],
            capture_output=True, text=True, timeout=5
        )
        if "paper-loop" in wmic.stdout or "paper_loop" in wmic.stdout:
            return jsonify({"running": True})
    except Exception:
        pass
    return jsonify({"running": False})


def _kill_existing_bot() -> None:
    """Kill any running paper-loop process regardless of how it was started."""
    global _bot_process
    # Kill our own handle first.
    if _bot_process is not None:
        try:
            _bot_process.terminate()
        except Exception:
            pass
        _bot_process = None
    # Also kill any externally-started bot via wmic.
    try:
        wmic = subprocess.run(
            ["wmic", "process", "where", "name='python.exe'", "get", "processid,commandline", "/format:list"],
            capture_output=True, text=True, timeout=5
        )
        # Parse wmic output: group CommandLine= and ProcessId= lines by process block
        current_cmd = ""
        for line in wmic.stdout.splitlines():
            if line.startswith("CommandLine="):
                current_cmd = line
            elif line.startswith("ProcessId=") and ("paper-loop" in current_cmd or "paper_loop" in current_cmd):
                pid = line.split("=", 1)[1].strip()
                if pid:
                    subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True)
    except Exception:
        pass


@app.route("/api/bot/start", methods=["POST"])
def bot_start():
    global _bot_process
    # Kill any existing instance first so we never double-start.
    _kill_existing_bot()
    import time as _time
    _time.sleep(1)
    root = Path(__file__).resolve().parents[2]
    log_path = root / "bot.log"
    log_file = open(log_path, "a")
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    _bot_process = subprocess.Popen(
        ["uv", "run", "main.py", "paper-loop"],
        cwd=root,
        stdout=log_file,
        stderr=log_file,
        env=env,
    )
    # Close our handle — the child process keeps its own fd open for writing.
    # Leaving this open would lock the file on Windows, preventing reads/rotation.
    log_file.close()
    return jsonify({"ok": True, "message": "Bot started"})


@app.route("/api/bot/stop", methods=["POST"])
def bot_stop():
    _kill_existing_bot()
    return jsonify({"ok": True, "message": "Bot stopped"})


_REC_JSON = Path(__file__).resolve().parents[2] / "advisor_recommendations.json"


@app.route("/api/recommendations")
def recommendations():
    if not _REC_JSON.exists():
        return jsonify({"available": False})
    try:
        rec = json.loads(_REC_JSON.read_text(encoding="utf-8"))
    except Exception:
        return jsonify({"available": False})
    if rec.get("applied") or rec.get("dismissed"):
        return jsonify({"available": False})
    return jsonify({"available": True, "data": rec})


@app.route("/api/recommendations/apply", methods=["POST"])
def recommendations_apply():
    import re
    import time as _time
    from datetime import datetime, timezone

    if not _REC_JSON.exists():
        return jsonify({"ok": False, "error": "No recommendations file"}), 404

    try:
        rec = json.loads(_REC_JSON.read_text(encoding="utf-8"))
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    root = Path(__file__).resolve().parents[2]
    env_path = root / ".env"
    if not env_path.exists():
        return jsonify({"ok": False, "error": ".env not found"}), 404

    env_text = env_path.read_text(encoding="utf-8")
    applied = []
    for ch in rec.get("changes", []):
        param = ch.get("param", "").strip()
        recommended = str(ch.get("recommended", "")).strip()
        if not param or not recommended:
            continue
        new_text, n = re.subn(
            rf"^({re.escape(param)}=).*$",
            f"{param}={recommended}",
            env_text, flags=re.MULTILINE,
        )
        if n > 0:
            env_text = new_text
            applied.append(param)

    env_path.write_text(env_text, encoding="utf-8")

    rec["applied"] = True
    rec["applied_at"] = datetime.now(timezone.utc).isoformat()
    _REC_JSON.write_text(json.dumps(rec, indent=2), encoding="utf-8")

    # Restart bot: kill existing then re-schedule via task scheduler.
    _kill_existing_bot()
    _time.sleep(1)
    subprocess.run(["schtasks", "/run", "/tn", "PolyBot"], capture_output=True)

    return jsonify({"ok": True, "applied": applied})


@app.route("/api/recommendations/dismiss", methods=["POST"])
def recommendations_dismiss():
    if not _REC_JSON.exists():
        return jsonify({"ok": False}), 404
    try:
        rec = json.loads(_REC_JSON.read_text(encoding="utf-8"))
        rec["dismissed"] = True
        _REC_JSON.write_text(json.dumps(rec, indent=2), encoding="utf-8")
    except Exception:
        pass
    return jsonify({"ok": True})


def run(host: str = "0.0.0.0", port: int = 5000, debug: bool = False) -> None:
    app.run(host=host, port=port, debug=debug)
