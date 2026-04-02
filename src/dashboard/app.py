from __future__ import annotations

import json
import csv
import time
from pathlib import Path

from flask import Flask, jsonify, render_template

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
    """Return last 80 lines of bot.log for live monitoring."""
    log_path = Path(__file__).resolve().parents[2] / "bot.log"
    if not log_path.exists():
        return jsonify({"lines": []})
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        return jsonify({"lines": lines[-80:]})
    except Exception:
        return jsonify({"lines": []})
