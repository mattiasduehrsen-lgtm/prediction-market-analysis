from __future__ import annotations

import csv
import json
import re
from pathlib import Path

from flask import Flask, jsonify, render_template

# Price-tick lines: [HH:MM:SS] BTC UP=0.505 DOWN=0.495 | 179s left
_PRICE_TICK = re.compile(r"^\[\d{2}:\d{2}:\d{2}\] \w+ UP=")

OUT_5M = Path(__file__).resolve().parents[2] / "output/5m_trading"

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


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/summary")
def api_summary():
    data = _read_json(OUT_5M / "summary.json")
    return jsonify(data)


@app.route("/api/positions")
def api_positions():
    rows = _read_csv(OUT_5M / "positions.csv")
    return jsonify(rows)


@app.route("/api/trades")
def api_trades():
    rows = _read_csv(OUT_5M / "trades.csv")
    return jsonify(rows[-100:])


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
