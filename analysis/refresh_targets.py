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
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ES_DIR = ROOT / "cowork_snapshot" / "esports"
PY = ROOT / ".venv" / "Scripts" / "python.exe"


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
    print(f"[refresh-targets] start {time.strftime('%Y-%m-%d %H:%M:%S')}", flush=True)
    # 1 — rebuild index (skips markets it already has via cursor; cheap if no churn)
    run("build_clob_index", ["analysis/build_clob_index.py"])

    # 2 — resumable trades scrape; only fetches new markets (manifest-driven)
    run("scrape_esports_trades", ["analysis/scrape_esports_trades.py"])

    # 3 — re-resolve outcomes (no API calls — reads from index parquet)
    run("resolve_outcomes", ["analysis/resolve_outcomes.py"])

    # 4 — refresh active fade targets
    run("identify_active_targets", ["analysis/identify_active_targets.py"])

    # Verify final file looks sane
    p = ES_DIR / "fade_targets.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    n = len(d.get("target_wallets") or [])
    print(f"\n[refresh-targets] done. fade_targets.json has {n} wallets.", flush=True)
    if n < 50:
        print("[refresh-targets] WARNING: target count looks low — investigate", flush=True)


if __name__ == "__main__":
    main()
