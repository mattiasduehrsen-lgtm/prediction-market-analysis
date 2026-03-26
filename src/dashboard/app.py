from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd
from flask import Flask, jsonify, render_template

OUTPUT_DIR = Path("output/paper_trading/polymarket")

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
    return jsonify([{k: r.get(k) for k in keep} for r in rows])


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


@app.route("/api/bot/status")
def bot_status():
    global _bot_process
    running = _bot_process is not None and _bot_process.poll() is None
    return jsonify({"running": running})


@app.route("/api/bot/start", methods=["POST"])
def bot_start():
    global _bot_process
    if _bot_process is not None and _bot_process.poll() is None:
        return jsonify({"ok": False, "message": "Bot is already running"})
    uv = os.path.join(sys.prefix, "..", "..", "bin", "uv")
    _bot_process = subprocess.Popen(
        ["uv", "run", "main.py", "paper-loop"],
        cwd=Path(__file__).resolve().parents[2],
    )
    return jsonify({"ok": True, "message": "Bot started"})


@app.route("/api/bot/stop", methods=["POST"])
def bot_stop():
    global _bot_process
    if _bot_process is None or _bot_process.poll() is not None:
        return jsonify({"ok": False, "message": "Bot is not running"})
    _bot_process.terminate()
    _bot_process = None
    return jsonify({"ok": True, "message": "Bot stopped"})


def run(host: str = "0.0.0.0", port: int = 5000, debug: bool = False) -> None:
    app.run(host=host, port=port, debug=debug)
