"""
Daily summary writer. Reads trades.csv + skipped_windows.csv + bot.log + LIVE
trade CSVs and produces a one-page summary for the day.

Output: output/daily_summary/YYYY-MM-DD.json + a human-readable .md alongside.

Usage:
  .venv\\Scripts\\python.exe daily_summary.py            # today
  .venv\\Scripts\\python.exe daily_summary.py 2026-05-12 # specific date

Designed to be run by a Windows scheduled task daily at 23:55 local time.
"""
from __future__ import annotations

import csv
import json
import re
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT       = Path(__file__).resolve().parent
OUT_5M     = ROOT / "output/5m_trading"
OUT_LIVE   = ROOT / "output/5m_live"
SUMMARY_DIR = ROOT / "output/daily_summary"
SUMMARY_DIR.mkdir(parents=True, exist_ok=True)

DISCOUNT = 0.955   # v1.28 share-fill discount


def _parse_date(s: str | None) -> datetime:
    if s is None:
        return datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def _read_csv(p: Path) -> list[dict]:
    if not p.exists():
        return []
    with p.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _f(s) -> float:
    try:
        return float(s) if s not in (None, "") else 0.0
    except (TypeError, ValueError):
        return 0.0


def corrected_pnl(row: dict) -> float:
    """Apply v1.28 share/TP corrections to a historical trade row."""
    size_usd = _f(row.get("size_usd"))
    entry_price = _f(row.get("entry_price"))
    if entry_price <= 0:
        return _f(row.get("pnl_usd"))
    correct_shares = round((size_usd / entry_price) * DISCOUNT, 2)
    exit_p = _f(row.get("take_profit")) if row.get("exit_reason") == "take_profit" else _f(row.get("exit_price"))
    return correct_shares * exit_p - size_usd


def summarize_paper(target_day: datetime) -> dict:
    end_ts = (target_day + timedelta(days=1)).timestamp()
    start_ts = target_day.timestamp()
    rows = _read_csv(OUT_5M / "trades.csv")
    day_rows = [r for r in rows
                if r.get("strategy") == "mean_reversion"
                and start_ts <= _f(r.get("closed_at")) < end_ts]

    if not day_rows:
        return {"n": 0, "wr_pct": None, "pnl_old": 0.0, "pnl_v1_28": 0.0,
                "by_asset_window": {}, "by_exit_reason": {}}

    by_aw = {}
    for r in day_rows:
        key = f"{r.get('asset', '?').upper()}-{r.get('window', '?')}"
        b = by_aw.setdefault(key, {"n": 0, "wins": 0, "pnl_old": 0.0, "pnl_v1_28": 0.0})
        b["n"] += 1
        p_old = _f(r.get("pnl_usd"))
        p_new = corrected_pnl(r)
        b["pnl_old"] += p_old
        b["pnl_v1_28"] += p_new
        if p_old > 0:
            b["wins"] += 1
    for v in by_aw.values():
        v["wr_pct"] = round(100.0 * v["wins"] / v["n"], 1) if v["n"] else None
        v["pnl_old"] = round(v["pnl_old"], 2)
        v["pnl_v1_28"] = round(v["pnl_v1_28"], 2)

    exit_counts = Counter(r.get("exit_reason", "?") for r in day_rows)
    wins = sum(1 for r in day_rows if _f(r.get("pnl_usd")) > 0)
    return {
        "n": len(day_rows),
        "wins": wins,
        "wr_pct": round(100.0 * wins / len(day_rows), 1),
        "pnl_old": round(sum(_f(r.get("pnl_usd")) for r in day_rows), 2),
        "pnl_v1_28": round(sum(corrected_pnl(r) for r in day_rows), 2),
        "by_asset_window": by_aw,
        "by_exit_reason": dict(exit_counts),
    }


def summarize_live(target_day: datetime) -> dict:
    """Aggregate LIVE trades from per-asset CSVs."""
    end_ts = (target_day + timedelta(days=1)).timestamp()
    start_ts = target_day.timestamp()
    all_rows = []
    for asset in ("BTC", "ETH", "SOL"):
        p = OUT_LIVE / f"trades_{asset}-15m.csv"
        for r in _read_csv(p):
            if start_ts <= _f(r.get("closed_at")) < end_ts:
                r["_asset"] = asset
                all_rows.append(r)
    if not all_rows:
        return {"n": 0, "wr_pct": None, "pnl": 0.0, "by_asset": {}}

    by_asset = {}
    for r in all_rows:
        b = by_asset.setdefault(r["_asset"], {"n": 0, "wins": 0, "pnl": 0.0})
        b["n"] += 1
        pnl = _f(r.get("pnl_usd"))
        b["pnl"] += pnl
        if pnl > 0:
            b["wins"] += 1
    for v in by_asset.values():
        v["wr_pct"] = round(100.0 * v["wins"] / v["n"], 1) if v["n"] else None
        v["pnl"] = round(v["pnl"], 2)

    wins = sum(1 for r in all_rows if _f(r.get("pnl_usd")) > 0)
    return {
        "n": len(all_rows),
        "wins": wins,
        "wr_pct": round(100.0 * wins / len(all_rows), 1),
        "pnl": round(sum(_f(r.get("pnl_usd")) for r in all_rows), 2),
        "by_asset": by_asset,
    }


def summarize_skips(target_day: datetime) -> dict:
    """Count skip reasons from skipped_windows.csv."""
    end_ts = (target_day + timedelta(days=1)).timestamp()
    start_ts = target_day.timestamp()
    p = OUT_5M / "skipped_windows.csv"
    if not p.exists():
        return {"n": 0, "by_reason": {}}
    rows = _read_csv(p)
    day_rows = [r for r in rows
                if start_ts <= _f(r.get("window_end_ts")) < end_ts]
    by_reason = Counter(r.get("skip_reason", "?") for r in day_rows)
    return {"n": len(day_rows), "by_reason": dict(by_reason.most_common(10))}


def summarize_brain(target_day: datetime) -> dict:
    """Count brain advice from bot.log scanned in time-window (best-effort)."""
    bot_log = ROOT / "bot.log"
    if not bot_log.exists():
        return {"n": 0, "by_mr_edge": {}}
    # Match: HH:MM:SS lines aren't dated, so we approximate by tail.
    # For a daily report run late-day, the tail captures today's calls.
    try:
        with bot_log.open("rb") as fh:
            fh.seek(max(0, bot_log.stat().st_size - 5 * 1024 * 1024))
            chunk = fh.read().decode("utf-8", errors="replace")
    except Exception:
        return {"n": 0, "by_mr_edge": {}}
    rx = re.compile(r"\[BRAIN\]\s+\w+\s+regime=\w+\s+mr_edge=(\w+)\s+modifier=([+\-][0-9.]+)")
    edges = []
    mods = []
    for line in chunk.splitlines():
        m = rx.search(line)
        if m:
            edges.append(m.group(1))
            mods.append(float(m.group(2)))
    return {
        "n": len(edges),
        "by_mr_edge": dict(Counter(edges)),
        "modifier_mean": round(sum(mods) / len(mods), 4) if mods else None,
        "note": "bot.log is not timestamped to date — counts may include up to 24h history",
    }


def write_summary(target_day: datetime, summary: dict) -> tuple[Path, Path]:
    date_str = target_day.strftime("%Y-%m-%d")
    json_path = SUMMARY_DIR / f"{date_str}.json"
    md_path   = SUMMARY_DIR / f"{date_str}.md"

    json_path.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")

    p = summary["paper"]; l = summary["live"]; s = summary["skips"]; b = summary["brain"]
    md_lines = [
        f"# Daily summary - {date_str} UTC", "",
        f"Generated: {summary['generated_at']}", "",
        "## PAPER", "",
        f"- Trades: {p['n']}  WR: {p['wr_pct'] if p['wr_pct'] is not None else '-'}%  "
        f"PnL (old): ${p['pnl_old']:+.2f}  PnL (v1.28): ${p['pnl_v1_28']:+.2f}",
        "",
    ]
    if p["by_asset_window"]:
        md_lines.append("### By asset/window")
        md_lines.append("| Segment | n | WR | PnL_old | PnL_v1.28 |")
        md_lines.append("|---|---|---|---|---|")
        for k, v in sorted(p["by_asset_window"].items()):
            md_lines.append(f"| {k} | {v['n']} | {v['wr_pct']}% | ${v['pnl_old']:+.2f} | ${v['pnl_v1_28']:+.2f} |")
        md_lines.append("")
    if p["by_exit_reason"]:
        md_lines.append("### By exit reason: " + ", ".join(f"{k}={v}" for k, v in p['by_exit_reason'].items()))
        md_lines.append("")
    md_lines.extend([
        "## LIVE", "",
        f"- Trades: {l['n']}  WR: {l['wr_pct'] if l['wr_pct'] is not None else '-'}%  "
        f"PnL: ${l['pnl']:+.2f}", "",
    ])
    if l["by_asset"]:
        md_lines.append("### By asset")
        for k, v in sorted(l["by_asset"].items()):
            md_lines.append(f"- {k}: n={v['n']}  WR={v['wr_pct']}%  PnL=${v['pnl']:+.2f}")
        md_lines.append("")
    md_lines.extend([
        "## Skips", "",
        f"- Windows skipped: {s['n']}", "",
    ])
    if s["by_reason"]:
        md_lines.append("### Top skip reasons: " + ", ".join(f"{k}={v}" for k, v in s["by_reason"].items()))
        md_lines.append("")
    md_lines.extend([
        "## Brain (research observation - ETH-15m only)", "",
        f"- Calls (last ~5MB of log): {b['n']}",
        f"- mr_edge counts: {b['by_mr_edge']}",
        f"- modifier mean: {b['modifier_mean']}",
    ])
    md_path.write_text("\n".join(md_lines), encoding="utf-8")
    return json_path, md_path


def main():
    target_day = _parse_date(sys.argv[1] if len(sys.argv) > 1 else None)

    summary = {
        "date":         target_day.strftime("%Y-%m-%d"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "paper":        summarize_paper(target_day),
        "live":         summarize_live(target_day),
        "skips":        summarize_skips(target_day),
        "brain":        summarize_brain(target_day),
    }
    json_path, md_path = write_summary(target_day, summary)
    print(f"[daily_summary] wrote {json_path}")
    print(f"[daily_summary] wrote {md_path}")
    print(f"  PAPER: n={summary['paper']['n']}  PnL_v1.28=${summary['paper'].get('pnl_v1_28', 0):+.2f}")
    print(f"  LIVE:  n={summary['live']['n']}   PnL=${summary['live'].get('pnl', 0):+.2f}")


if __name__ == "__main__":
    main()
