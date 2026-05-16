"""
Pre-LIVE sanity check — verifies everything the bot needs to place real orders.

Runs:
  1. .env keys present + non-empty
  2. py_clob_client_v2 imports OK
  3. clob_auth.get_client() succeeds (L1 + L2 auth)
  4. get_balance_allowance() returns USDC collateral balance + allowance
  5. evaluate_live.py runs cleanly (writes empty live_daily_pnl.json if no orders)

Exit code 0 if all pass, 1 if any fail. Designed for one-shot pre-flight.
"""
from __future__ import annotations

import os
import sys
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = ROOT / ".venv" / "Scripts" / "python.exe"
# Make 'src.bot.clob_auth' importable regardless of CWD
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")


def check(name, ok, detail=""):
    icon = "OK " if ok else "X  "
    print(f"  {icon} {name}{(' — ' + detail) if detail else ''}")
    return ok


def main():
    print("== LIVE READINESS CHECK ==\n")
    all_ok = True

    # 1 — .env keys
    print("[1] Environment variables")
    required = [
        "POLYMARKET_PRIVATE_KEY",
        "POLYMARKET_API_KEY",
        "POLYMARKET_API_SECRET",
        "POLYMARKET_API_PASSPHRASE",
        "POLYMARKET_PROXY_ADDRESS",
        "POLYMARKET_SIGNATURE_TYPE",
    ]
    for k in required:
        v = (os.environ.get(k) or "").strip()
        all_ok &= check(k, bool(v), f"{len(v)} chars" if v else "missing/empty")

    # 2 — imports
    print("\n[2] Python imports")
    try:
        from py_clob_client_v2 import (
            ApiCreds, ClobClient, OrderArgs, OrderType,
            BalanceAllowanceParams, AssetType,
        )
        from py_clob_client_v2.order_builder.constants import BUY, SELL
        from py_clob_client_v2.constants import POLYGON
        all_ok &= check("py_clob_client_v2", True)
    except Exception as e:
        all_ok &= check("py_clob_client_v2", False, str(e))
        print("\nCannot proceed without py_clob_client_v2")
        sys.exit(1)

    try:
        from src.bot.clob_auth import get_client
        all_ok &= check("src.bot.clob_auth", True)
    except Exception as e:
        all_ok &= check("src.bot.clob_auth", False, str(e))
        sys.exit(1)

    # 3 — client init
    print("\n[3] CLOB client initialization")
    try:
        client = get_client()
        all_ok &= check("get_client()", True)
    except Exception as e:
        all_ok &= check("get_client()", False, str(e))
        sys.exit(1)

    # 4 — balance + allowance
    print("\n[4] On-chain balance")
    try:
        from py_clob_client_v2 import BalanceAllowanceParams, AssetType
        b = client.get_balance_allowance(BalanceAllowanceParams(asset_type=AssetType.COLLATERAL))
        bal_raw = b.get("balance", "0")
        allow_raw = b.get("allowance", "0")
        bal_usd = int(bal_raw) / 1_000_000
        allow_usd = int(allow_raw) / 1_000_000
        check("balance fetched", True, f"${bal_usd:.4f} USDC available")
        check("allowance fetched", True, f"${allow_usd:.4f} USDC")
        # Sanity: need at least one day's risk cap available
        all_ok &= check("balance >= $50 (one day's risk cap)", bal_usd >= 50.0,
                        f"got ${bal_usd:.2f}")
        all_ok &= check("allowance >= $50", allow_usd >= 50.0,
                        f"got ${allow_usd:.2f}")
    except Exception as e:
        all_ok &= check("balance check", False, str(e))

    # 5 — evaluate_live.py dry run
    print("\n[5] LIVE PnL evaluator")
    eval_path = ROOT / "analysis" / "evaluate_live.py"
    if eval_path.exists():
        r = subprocess.run([str(PY), str(eval_path)], capture_output=True, text=True, timeout=60)
        all_ok &= check("evaluate_live.py exits clean", r.returncode == 0,
                        r.stderr.strip().splitlines()[-1] if r.stderr else "")
    else:
        all_ok &= check("evaluate_live.py exists", False, str(eval_path))

    # 6 — output dir writable
    print("\n[6] Output paths")
    out_dir = ROOT / "output" / "esports_fade"
    all_ok &= check("output dir exists", out_dir.exists(), str(out_dir))
    test_file = out_dir / ".write_test"
    try:
        test_file.write_text("ok", encoding="utf-8")
        test_file.unlink()
        all_ok &= check("output dir writable", True)
    except Exception as e:
        all_ok &= check("output dir writable", False, str(e))

    print()
    if all_ok:
        print("ALL CHECKS PASSED — system is ready for LIVE.")
        print("To flip: run  go_live.bat  on the laptop.")
        sys.exit(0)
    else:
        print("ONE OR MORE CHECKS FAILED — do not enable LIVE until fixed.")
        print("\nLikely remediation:")
        print("  - balance < $50      : send USDC to the funder wallet (POLYMARKET_PROXY_ADDRESS in .env)")
        print("  - allowance < $50    : run  .venv\\Scripts\\python.exe analysis\\setup_live_allowances.py --confirm")
        print("  - missing env vars   : verify .env on laptop has CLOB credentials (see DEPLOY_ESPORTS_FADE.md)")
        sys.exit(1)


if __name__ == "__main__":
    main()
