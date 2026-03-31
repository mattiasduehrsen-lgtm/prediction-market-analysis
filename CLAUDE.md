# Prediction Market Bot — Claude Context

## Project overview

Paper-trading bot that arbitrages price discrepancies between Polymarket and Kalshi. The bot runs continuously on a laptop, cycles every 3 minutes, and accumulates closed trade data toward a 50-trade milestone for ML-based strategy improvement via Claude Desktop Cowork.

## Two-machine setup — CRITICAL

**This PC (development):** `C:\Users\home user\Desktop\prediction-market-analysis`
- Used for code edits, git commits, pushing

**Laptop (production):** `C:\Users\matti\Desktop\prediction-market-analysis`
- Runs the bot 24/7, IP: `192.168.2.212`
- SSH: `ssh matti@192.168.2.212` (password: Tiasdue123.)

Code changes must be: edited here → `git push` → `git pull` on laptop → restart bot on laptop.

## The bot is always running — be careful

The bot is in active paper-trading data collection. Every code change that touches `src/bot/polymarket.py`, `main.py`, or `src/current/collector.py` requires a restart on the laptop to take effect. Do not make speculative or architectural changes — only fix what is explicitly asked.

## .env is NOT git-tracked

The `.env` file exists on both machines independently and is never committed. Changes to `.env` must be applied manually on each machine. The laptop's `.env` is at `C:\Users\matti\Desktop\prediction-market-analysis\.env`.

Current `.env` values (both machines should match):
```
PAPER_EDGE_THRESHOLD=0.008
PAPER_EDGE_RATIO_THRESHOLD=0.01
PAPER_MIN_RECENT_TRADES=1
PAPER_MIN_RECENT_NOTIONAL=0.5
PAPER_MIN_BUY_SHARE=0.55
PAPER_MIN_LIQUIDITY=5000.0
PAPER_MAX_HOURS_TO_EXPIRY=8760.0
PAPER_MAX_POSITIONS=50
PAPER_MAX_CANDIDATES=20
PAPER_LOOKBACK_SECONDS=1800
PAPER_LOOP_SLEEP_SECONDS=180
PAPER_MAX_SECONDS_SINCE_LAST_TRADE=3600
PAPER_TAKE_PROFIT_PCT=0.15
PAPER_STOP_LOSS_PCT=0.07
PAPER_MAX_HOLDING_SECONDS=28800
PAPER_MAX_FALLBACK_SECONDS=60
```

## Restarting the bot (laptop, via SSH)

```powershell
Stop-Process -Name python -Force
schtasks /run /tn PolyBot
schtasks /run /tn PolyDashboard
```

Never use `Start-Process` via SSH to start the bot — it ties the process to the SSH session and dies when the terminal closes. Always use `schtasks /run`.

## Checking bot health (laptop, via SSH)

```powershell
# Last few iterations
Get-Content "C:\Users\matti\Desktop\prediction-market-analysis\bot.log" -Tail 30

# Equity and trade count
Select-String -Path "C:\Users\matti\Desktop\prediction-market-analysis\bot.log" -Pattern "equity=" | Select-Object -Last 3
```

## Known critical bugs — do not re-introduce

1. **Never use `(left_ts - right_ts)` for Kalshi timestamps** — pandas raises `KeyboardInterrupt` from C-level on overflow. Use `int(left_ts.value) - int(right_ts.value)` arithmetic in `_time_alignment_score` (polymarket.py ~line 249).

2. **Never remove `write_through=True`** from the `io.TextIOWrapper` calls in `main.py` — without it, bot.log stays empty when running as a background process.

3. **Never remove the `try/except BaseException: pass`** around `_time.sleep(1)` in the between-cycle loop in `main.py` — the pandas SIGINT fires late during sleep after `run_once()` completes.

4. **Never set `PAPER_MAX_FALLBACK_SECONDS` above 120** without testing — stale entry prices trigger immediate stop-losses.

## Strategy context

- Cross-market arbitrage: Polymarket vs Kalshi price gaps
- All wins are `kalshi_confirmed` — Kalshi confirmation is necessary for profitable trades
- edge=0.005 trades avg -$3.90 (noise), edge=0.010+ trades avg +$21.79 (real signal)
- Stop-loss exits avg -$9.42 — almost always from entering at stale prices
- Take-profit exits avg +$32.84 — wins are large when the signal is real
- 88% of candidate markets have zero recent trades — liquidity is the core constraint

## Language and toolchain

- Python 3.11, managed with `uv`
- No TypeScript, no ESLint, no tsc — do not run JS/TS tooling
- Dependencies in `pyproject.toml`
- Run bot: `.venv\Scripts\python.exe -u main.py paper-loop`
- Run dashboard: `.venv\Scripts\python.exe -u main.py dashboard`

## Current phase

Data collection — accumulating 50+ closed trades for Cowork-based ML analysis. Do not make large structural changes to signal logic or scoring until after Cowork has analyzed the trade data and identified what to improve. Incremental, targeted fixes only.
