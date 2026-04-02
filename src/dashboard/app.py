from __future__ import annotations

import json
import csv
from pathlib import Path

from flask import Flask, jsonify, render_template

OUT_DIR = Path(__file__).resolve().parents[2] / "output/btc_trading"

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
    data = _read_json(OUT_DIR / "summary.json")
    return jsonify(data)


@app.route("/api/positions")
def api_positions():
    rows = _read_csv(OUT_DIR / "positions.csv")
    return jsonify(rows)


@app.route("/api/trades")
def api_trades():
    rows = _read_csv(OUT_DIR / "trades.csv")
    # Return most recent 100
    return jsonify(rows[-100:])


@app.route("/api/markets")
def api_markets():
    data = _read_json(OUT_DIR / "markets_cache.json")
    markets = data.get("markets", [])
    return jsonify({
        "event_title": data.get("event_title", ""),
        "event_end": data.get("event_end", ""),
        "markets": markets,
    })
