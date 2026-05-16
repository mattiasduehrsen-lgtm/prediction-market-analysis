"""
Refresh fade_targets.json end-to-end on the laptop.

Pipeline:
  1. Rebuild CLOB esports market index (resumable)
  2. Re-scrape trades for new/unresolved markets (resumable per-market)
  3. Re-resolve outcomes from CLOB winner field
  4. Re-identify active losing wallets (CS2, last 14d, ROI<-5%, n>=30)
  5. Atomic-replace cowork_snapshot/esports/fade_targets.json

Bot auto-detects the new file via mtime check in its poll loop (no restart needed).

Designed to be invoked from a scheduled task. Logs to stdout (caller redirects
to refresh.log).

Idempotent and safe to interrupt — each step is resumable.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ES_DIR = ROOT / "cowork_snapshot" / "esports"
PY = ROOT / ".venv" / "Scripts" / "python.exe"
LOCK = ROOT / "output" / "esports_fade" / "refresh.lock"


def run(name: str, args: list[str], must_succeed: bool = True) -> int:
    print(f"\n=== {name} ===", flush=True)
    t0 = time.time()
    r = subprocess.run([str(PY)] + args, cwd=str(ROOT))
    dt = time.time() - t0
    print(f"--- {name} done rc={r.returncode} ({dt:.1f}s) ---", flush=True)
    if must_succeed and r.returncode != 0:
        raise SystemExit(f"step '{name}' failed (rc={r.returncode})")
    return r.returncode


def main():
    # Single-instance lock — if a previous refresh is still running, bail.
    # Lockfile contains pid + start time; stale locks (>2h) auto-cleared.
    if LOCK.exists():
        try:
            content = LOCK.read_text(encoding="utf-8").strip()
            pid_str, ts_str = (content.split("|", 1) + [""])[:2]
            start = float(ts_str) if ts_str else 0
            age = time.time() - start
            if age < 2 * 3600:
                print(f"[refresh-targets] previous run still active "
                      f"(pid={pid_str}, age={age:.0f}s) — exit", flush=True)
                return
            print(f"[refresh-targets] stale lock (age={age:.0f}s) — overriding", flush=True)
        except Exception:
            pass
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    LOCK.write_text(f"{os.getpid()}|{time.time()}", encoding="utf-8")

    try:
        print(f"[refresh-targets] start {time.strftime('%Y-%m-%d %H:%M:%S')}", flush=True)
        _run_pipeline()
    finally:
        try:
            LOCK.unlink()
        except Exception:
            pass


def _run_pipeline():
    # 1 — rebuild index (skips markets it already has via cursor; cheap if no churn)
    run("build_clob_index", ["analysis/build_clob_index.py"])

    # 2 — resumable trades scrape; only fetches new markets (manifest-driven)
    run("scrape_esports_trades", ["analysis/scrape_esports_trades.py"])

    # 3 — re-resolve outcomes (no API calls — reads from index parquet)
    run("resolve_outcomes", ["analysis/resolve_outcomes.py"])

    # 4 — refresh active fade targets (losers to fade)
    run("identify_active_targets", ["analysis/identify_active_targets.py"])

    # 5 — refresh follow targets (winners to copy)
    run("identify_active_winners", ["analysis/identify_active_winners.py"])

    # Verify final file looks sane
    p = ES_DIR / "fade_targets.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    n = len(d.get("target_wallets") or [])
    print(f"\n[refresh-targets] done. fade_targets.json has {n} wallets.", flush=True)
    if n < 50:
        print("[refresh-targets] WARNING: target count looks low — investigate", flush=True)


if __name__ == "__main__":
    main()
