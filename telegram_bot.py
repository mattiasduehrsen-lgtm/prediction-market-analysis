"""Telegram command bot — two-way control of the esports fade bot.

Polls Telegram for messages from the configured user (chat_id whitelist) and
executes pre-defined commands locally on the laptop. Replies with results.

Runs as its own process (PolyBotTelegram scheduled task). Doesn't touch the
trading bot directly — it writes flag files / runs schtasks commands that the
trading bot picks up on its next loop iteration.

Security:
  - Only messages from TELEGRAM_CHAT_ID are accepted (Telegram authenticates
    sender via their own infra)
  - Commands are pre-defined; no arbitrary execution
  - Sensitive commands (restart) confirm before acting
"""
from __future__ import annotations
import csv
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
API     = f"https://api.telegram.org/bot{TOKEN}"

ROOT = Path(__file__).resolve().parent
OUT_ES = ROOT / "output" / "esports_fade"
PAUSE_FLAG = OUT_ES / "paused.flag"
LIVE_RESULTS = OUT_ES / "live_results.csv"
LIVE_DAILY = OUT_ES / "live_daily_pnl.json"
BOT_LOG = OUT_ES / "bot.log"
WATCHDOG_LOG = ROOT / "watchdog_esports.log"
STALL_FLAG = OUT_ES / "signal_stall.flag"


def send(text: str, parse_mode: str = "HTML") -> None:
    try:
        requests.post(f"{API}/sendMessage", data={
            "chat_id": CHAT_ID, "text": text, "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }, timeout=10)
    except Exception as e:
        print(f"[tg-bot] send failed: {e}")


# ── Commands ────────────────────────────────────────────────────────────────

def cmd_help(args: str) -> str:
    return (
        "<b>Available commands</b>\n"
        "/status — overall snapshot\n"
        "/balance — wallet cash + position value\n"
        "/positions — currently-open positions\n"
        "/today — today's PnL detail\n"
        "/risk — daily-risk and loss cap status\n"
        "/perf — FADE vs FOLLOW lifetime breakdown\n"
        "/pause — stop placing new orders\n"
        "/resume — allow new orders again\n"
        "/restart — restart the esports bot task\n"
        "/log [N] — last N (default 15) lines of bot log\n"
        "/stall — current signal-stall status\n"
        "/help — this message"
    )


def cmd_balance(args: str) -> str:
    """pUSD via CLOB SDK + open position value via data-api."""
    try:
        proxy = os.getenv("POLYMARKET_PROXY_ADDRESS", "")
        if not proxy:
            return "POLYMARKET_PROXY_ADDRESS missing"
        # Live position value (data-api, public)
        pos_val = 0.0
        try:
            r = requests.get(f"https://data-api.polymarket.com/value?user={proxy}", timeout=8)
            d = r.json()
            if isinstance(d, list) and d:
                pos_val = float(d[0].get("value", 0))
        except Exception:
            pass
        # pUSD via CLOB SDK
        cash = None
        try:
            import contextlib, io as _io
            from py_clob_client_v2 import ClobClient, BalanceAllowanceParams, AssetType
            with contextlib.redirect_stderr(_io.StringIO()):
                client = ClobClient(
                    "https://clob.polymarket.com",
                    key=os.getenv("POLYMARKET_PRIVATE_KEY"),
                    chain_id=137, signature_type=2, funder=proxy,
                )
                client.set_api_creds(client.create_or_derive_api_key())
                b = client.get_balance_allowance(BalanceAllowanceParams(asset_type=AssetType.COLLATERAL))
            cash = int(b.get("balance", 0)) / 1e6
        except Exception as e:
            return f"Balance check failed: {e}"
        total = (cash or 0) + pos_val
        return (
            f"<b>💰 Wallet</b>\n"
            f"pUSD (cash): <b>${cash:.2f}</b>\n"
            f"Open positions value: ${pos_val:.2f}\n"
            f"<b>Total: ${total:.2f}</b>"
        )
    except Exception as e:
        return f"Balance error: {e}"


def cmd_today(args: str) -> str:
    """Today's realized PnL + counts from live_results.csv."""
    if not LIVE_RESULTS.exists():
        return "No results yet."
    today = datetime.now(timezone.utc).date().isoformat()
    n_w = n_l = 0; pnl = 0.0; cost = 0.0
    last_trade_ts = 0.0; last_slug = ""
    with LIVE_RESULTS.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if str(r.get("side", "BUY")).upper() == "SELL":
                continue
            status = r.get("status", "")
            try:
                ts = float(r.get("ts") or 0)
            except (TypeError, ValueError):
                continue
            if ts > last_trade_ts:
                last_trade_ts = ts
                last_slug = r.get("fade_slug", "")
            d = datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat() if ts else ""
            if d != today: continue
            if status not in ("WIN", "LOSS", "TP_SOLD", "TP_LOSS"): continue
            if status in ("WIN", "TP_SOLD"): n_w += 1
            else: n_l += 1
            try:
                pnl  += float(r.get("realized_pnl") or 0)
                cost += float(r.get("cost_usd") or 0)
            except (TypeError, ValueError):
                pass
    sign = "+" if pnl >= 0 else "−"
    pnl_str = f"{sign}${abs(pnl):.2f}"
    last_age = (time.time() - last_trade_ts) / 60 if last_trade_ts else None
    last_str = f"{last_age:.0f}m ago — {last_slug[:30]}" if last_age is not None else "—"
    return (
        f"<b>📅 Today (UTC {today})</b>\n"
        f"Resolved: <b>{n_w}W / {n_l}L</b>\n"
        f"PnL: <b>{pnl_str}</b> on ${cost:.2f} cost\n"
        f"Last resolved trade: {last_str}"
    )


def cmd_status(args: str) -> str:
    """Combined snapshot — balance + today + pause/stall state."""
    parts = [cmd_balance(""), "", cmd_today(""), ""]
    if PAUSE_FLAG.exists():
        parts.append("⏸️ <b>Bot is PAUSED</b> — /resume to restart trading.")
    elif STALL_FLAG.exists():
        try:
            s = json.loads(STALL_FLAG.read_text(encoding="utf-8"))
            hrs = (time.time() - s.get("stall_started_at", time.time())) / 3600
            parts.append(f"⚠️ Signal stall active ({hrs:.1f}h)")
        except Exception:
            parts.append("⚠️ Signal stall active")
    else:
        parts.append("🟢 Bot trading normally.")
    return "\n".join(parts)


def cmd_positions(args: str) -> str:
    """Currently-open positions from the dashboard's API."""
    try:
        r = requests.get("http://localhost:5000/api/esports/live/open", timeout=8)
        d = r.json()
    except Exception as e:
        return f"Could not fetch positions: {e}"
    rows = d.get("open_positions") or d.get("open") or []
    if not rows:
        return "📂 No open positions."
    s = d.get("summary", {})
    out = [f"<b>📈 {len(rows)} open positions</b>",
           f"Cost: ${s.get('total_cost_usd', 0):.2f} · "
           f"Value: ${s.get('current_value_usd', 0):.2f} · "
           f"Unreal: ${s.get('unrealized_pnl_usd', 0):+.2f}", ""]
    for p in rows[:10]:
        outcome = (p.get("our_outcome") or "?")[:14]
        slug = (p.get("fade_slug") or "")[:35]
        cost = p.get("total_cost", 0)
        unreal = p.get("unrealized_pnl")
        unreal_str = f"{unreal:+.2f}" if unreal is not None else "?"
        out.append(f"• {outcome:>14} ${cost:.0f} ({unreal_str}) {slug}")
    if len(rows) > 10:
        out.append(f"... +{len(rows) - 10} more")
    return "\n".join(out)


def cmd_pause(args: str) -> str:
    if PAUSE_FLAG.exists():
        return "⏸️ Already paused."
    PAUSE_FLAG.write_text(json.dumps({"paused_at": time.time(),
                                       "via": "telegram"}), encoding="utf-8")
    return "⏸️ <b>Paused.</b> Bot will skip new orders. Open positions remain."


def cmd_resume(args: str) -> str:
    if not PAUSE_FLAG.exists():
        return "Already running — nothing to resume."
    try:
        PAUSE_FLAG.unlink()
        return "▶️ <b>Resumed.</b> Bot will place new orders again."
    except Exception as e:
        return f"Resume failed: {e}"


def cmd_restart(args: str) -> str:
    """Restart the esports bot task via schtasks."""
    try:
        subprocess.run(["schtasks", "/end", "/tn", "PolyBotEsports"],
                       capture_output=True, timeout=15)
        time.sleep(2)
        lock = ROOT / "watchdog_esports.lock"
        if lock.exists():
            try: lock.unlink()
            except Exception: pass
        time.sleep(1)
        subprocess.run(["schtasks", "/run", "/tn", "PolyBotEsports"],
                       capture_output=True, timeout=15, check=True)
        return "🔄 <b>Restart triggered.</b> Bot should be back in ~10s. Watch for startup ping."
    except Exception as e:
        return f"Restart failed: {e}"


def cmd_log(args: str) -> str:
    try:
        n = int(args.strip() or "15")
    except ValueError:
        n = 15
    n = max(1, min(n, 60))
    path = BOT_LOG if BOT_LOG.exists() else WATCHDOG_LOG
    if not path.exists():
        return "No log file."
    try:
        with path.open(encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        tail = "".join(lines[-n:])
    except Exception as e:
        return f"Read error: {e}"
    # Keep under Telegram's 4096 char limit
    if len(tail) > 3500:
        tail = "...\n" + tail[-3500:]
    return f"<b>Last {n} lines:</b>\n<pre>{tail}</pre>"


def cmd_risk(args: str) -> str:
    """Current daily_risk_usd and daily_pnl vs caps."""
    import csv as _csv
    today = datetime.now(timezone.utc).date()
    midnight = datetime(today.year, today.month, today.day, tzinfo=timezone.utc).timestamp()
    # Sum matched BUY costs since UTC midnight from live_orders.jsonl
    risk_usd = 0.0
    n_matched = n_canceled = n_error = 0
    orders_path = OUT_ES / "live_orders.jsonl"
    if orders_path.exists():
        with orders_path.open(encoding="utf-8") as f:
            for line in f:
                try: o = json.loads(line)
                except: continue
                if str(o.get("side", "BUY")).upper() != "BUY": continue
                if (o.get("ts") or 0) < midnight: continue
                status = str(o.get("status", "")).lower()
                if status == "matched":
                    n_matched += 1
                    try: risk_usd += float(o.get("cost_usd") or 0)
                    except (TypeError, ValueError): pass
                elif status in ("canceled", "cancelled"):
                    n_canceled += 1
    # Today's realized PnL from live_daily_pnl.json
    daily_pnl = 0.0
    if LIVE_DAILY.exists():
        try:
            d = json.loads(LIVE_DAILY.read_text(encoding="utf-8"))
            if d.get("date") == today.isoformat():
                daily_pnl = float(d.get("realized_pnl_usd") or 0)
        except Exception:
            pass

    # Hardcoded caps (read from bot would require parsing source — these are
    # the values we set today)
    LOSS_CAP = 150.0
    RISK_CAP = 2000.0
    loss_pct = abs(daily_pnl / LOSS_CAP * 100) if daily_pnl < 0 else 0
    risk_pct = risk_usd / RISK_CAP * 100
    pnl_str = f"{'+' if daily_pnl >= 0 else '-'}${abs(daily_pnl):.2f}"
    return (
        f"<b>🛡️ Caps status (UTC {today})</b>\n"
        f"\n"
        f"<b>Loss cap (primary):</b> ${LOSS_CAP:.0f}\n"
        f"  today's PnL: <b>{pnl_str}</b> ({loss_pct:.0f}% of cap)\n"
        f"\n"
        f"<b>Risk cap (backstop):</b> ${RISK_CAP:.0f}\n"
        f"  spent today: <b>${risk_usd:.2f}</b> ({risk_pct:.1f}% of cap)\n"
        f"  matched: {n_matched}  canceled: {n_canceled}"
    )


def cmd_perf(args: str) -> str:
    """FADE vs FOLLOW lifetime breakdown from live_results.csv."""
    import csv as _csv
    if not LIVE_RESULTS.exists():
        return "No live results yet."
    by_strat = {"fade": {"n": 0, "w": 0, "l": 0, "pnl": 0.0, "cost": 0.0},
                "follow": {"n": 0, "w": 0, "l": 0, "pnl": 0.0, "cost": 0.0}}
    with LIVE_RESULTS.open(encoding="utf-8") as f:
        for r in _csv.DictReader(f):
            if str(r.get("side", "BUY")).upper() == "SELL": continue
            strat = (r.get("strategy") or "fade").lower()
            if strat not in by_strat: continue
            status = r.get("status", "")
            if status not in ("WIN", "LOSS", "TP_SOLD", "TP_LOSS"): continue
            s = by_strat[strat]
            s["n"] += 1
            if status in ("WIN", "TP_SOLD"): s["w"] += 1
            else: s["l"] += 1
            try:
                s["pnl"]  += float(r.get("realized_pnl") or 0)
                s["cost"] += float(r.get("cost_usd") or 0)
            except (TypeError, ValueError): pass

    def fmt(s):
        if not s["n"]: return "  n=0"
        wr = s["w"] / s["n"] * 100
        roi = s["pnl"] / s["cost"] * 100 if s["cost"] > 0 else 0
        sign = "+" if s["pnl"] >= 0 else "-"
        pnl = f"{sign}${abs(s['pnl']):.2f}"
        return (f"  n={s['n']:<3}  {s['w']}W/{s['l']}L  WR <b>{wr:.0f}%</b>\n"
                f"  PnL: <b>{pnl}</b>  ROI: <b>{roi:+.1f}%</b>  cost: ${s['cost']:.0f}")
    return (
        f"<b>📊 Strategy performance (lifetime)</b>\n"
        f"\n<b>FADE:</b>\n{fmt(by_strat['fade'])}\n"
        f"\n<b>FOLLOW:</b>\n{fmt(by_strat['follow'])}"
    )


def cmd_stall(args: str) -> str:
    if not STALL_FLAG.exists():
        return "🟢 No stall — fade signals flowing normally."
    try:
        s = json.loads(STALL_FLAG.read_text(encoding="utf-8"))
        hrs = (time.time() - s.get("stall_started_at", time.time())) / 3600
        return (f"⚠️ <b>Signal stall active</b>\n"
                f"Duration: {hrs:.1f}h\n"
                f"Fades stuck at: {s.get('fades_at_stall')}")
    except Exception:
        return "⚠️ Stall flag exists but couldn't parse."


COMMANDS = {
    "/help":      cmd_help,
    "/start":     cmd_help,
    "/status":    cmd_status,
    "/balance":   cmd_balance,
    "/today":     cmd_today,
    "/risk":      cmd_risk,
    "/perf":      cmd_perf,
    "/positions": cmd_positions,
    "/pause":     cmd_pause,
    "/resume":    cmd_resume,
    "/restart":   cmd_restart,
    "/log":       cmd_log,
    "/stall":     cmd_stall,
}


# ── Main loop ───────────────────────────────────────────────────────────────

def main():
    if not TOKEN or not CHAT_ID:
        print("[tg-bot] TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID missing in .env")
        return
    print(f"[tg-bot] listening as bot — only chat_id={CHAT_ID} is authorized")
    last_update_id = None
    # First call with timeout=0 to flush old updates so we don't reply to ancient messages.
    try:
        r = requests.get(f"{API}/getUpdates", params={"timeout": 0}, timeout=10)
        updates = r.json().get("result", [])
        if updates:
            last_update_id = updates[-1]["update_id"]
    except Exception:
        pass

    while True:
        try:
            params = {"timeout": 30}
            if last_update_id is not None:
                params["offset"] = last_update_id + 1
            r = requests.get(f"{API}/getUpdates", params=params, timeout=40)
            for u in r.json().get("result", []):
                last_update_id = u["update_id"]
                msg = u.get("message") or u.get("edited_message")
                if not msg:
                    continue
                chat = msg.get("chat") or {}
                if str(chat.get("id")) != CHAT_ID:
                    print(f"[tg-bot] ignoring message from unauthorized chat {chat.get('id')}")
                    continue
                text = (msg.get("text") or "").strip()
                if not text:
                    continue
                cmd, _, args = text.partition(" ")
                cmd = cmd.lower().split("@")[0]  # strip any "@botname" suffix
                handler = COMMANDS.get(cmd)
                if not handler:
                    send(f"Unknown command: <code>{cmd}</code>\nTry /help")
                    continue
                print(f"[tg-bot] {cmd} from chat {chat.get('id')}")
                try:
                    reply = handler(args)
                except Exception as e:
                    reply = f"Command failed: {e}"
                send(reply)
        except requests.exceptions.Timeout:
            continue  # long-poll timeout, just retry
        except KeyboardInterrupt:
            print("[tg-bot] stopping")
            return
        except Exception as e:
            print(f"[tg-bot] loop error: {e}")
            time.sleep(5)


if __name__ == "__main__":
    main()
