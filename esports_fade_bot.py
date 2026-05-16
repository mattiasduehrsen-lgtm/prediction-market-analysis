"""
Live fade-bottom-whale bot for Polymarket CS2 esports.

Monitors Polymarket's data-api for new trades. When a tracked target wallet
places a trade, we compute the opposite-side fade and (in PAPER mode) log it,
(in LIVE mode) place the trade via Polymarket CLOB.

Phase 1 = PAPER only. Run for a week to validate the live signal matches
backtest (+110% ROI expected). Phase 2 = LIVE with $5/trade and tight caps.

Usage:
  .venv\\Scripts\\python.exe esports_fade_bot.py            # PAPER mode
  .venv\\Scripts\\python.exe esports_fade_bot.py --live     # LIVE (disabled by default)
"""
from __future__ import annotations

import argparse
import csv as _csv
import json
import time
import threading
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv
load_dotenv()

ROOT = Path(__file__).resolve().parent
ES_DIR = ROOT / "cowork_snapshot" / "esports"
OUT_DIR = ROOT / "output" / "esports_fade"
OUT_DIR.mkdir(parents=True, exist_ok=True)

POLL_INTERVAL = 2.0           # seconds between API polls
RECENT_TRADES_LIMIT = 500     # how many recent trades to scan each poll
PAPER_BET_USD = 5.0           # bet size (PAPER)
LIVE_BET_USD = 5.0            # bet size (LIVE)
DAILY_LOSS_CAP = 50.0         # halt for the day if REALIZED losses exceed this (LIVE; future — see daily_risk_cap)
DAILY_RISK_CAP_USD = 50.0     # halt for the day after we've bet this much $ (LIVE, immediate)
MAX_PER_MARKET_USD = 10.0     # cumulative bet cap per (market, our_outcome)
MAX_FADES_PER_DAY = 100       # sanity ceiling on daily signal count
MIN_SECONDS_BETWEEN_SAME_TARGET_SAME_MARKET = 30  # debounce rapid repeats
ENTRY_SLIPPAGE = 0.01         # add 1c to our BUY price so order fills (v1.9 pattern)
MIN_ENTRY_PRICE = 0.05        # don't place orders below 5c (no depth)
MAX_ENTRY_PRICE = 0.95        # don't pay >95c (essentially resolved)
SEEN_TX_PRIME_LIMIT = 2000    # how many recent tx hashes to load from CSV on startup
LIVE_FILL_POLL_INTERVAL = 2.0 # seconds between fill checks
LIVE_FILL_TIMEOUT = 12.0      # cancel if not matched within this many seconds

# Games where per-game OOS backtest cleared ~+100% ROI on a real sample:
#   cs2/csgo (+144%), league-of-legends / league- (+127%).
# Dota/Valorant samples too small to trust right now — add later.
ESPORTS_PREFIXES = ("cs2-", "csgo-", "league-")


class FadeBot:
    def __init__(self, live: bool = False, dry_live: bool = False):
        # dry_live exercises the LIVE init path (auth, client) and the cap
        # arithmetic, but place_live_order returns before submitting.
        self.live = live
        self.dry_live = dry_live
        self.target_wallets = self._load_targets()
        self.seen_tx = deque(maxlen=10000)  # dedup
        self.seen_tx_set = set()
        self.session = requests.Session()
        self.papertrades_path = OUT_DIR / "paper_trades.csv"
        self.events_path = OUT_DIR / "fade_events.jsonl"
        self.live_orders_path = OUT_DIR / "live_orders.jsonl"
        self.client = None
        if live or dry_live:
            from src.bot.clob_auth import get_client
            self.client = get_client()
        self.daily_pnl = 0.0
        self.daily_pnl_mtime = 0.0
        self.daily_risk_usd = 0.0
        self.day_started = datetime.now(timezone.utc).date()
        self.daily_pnl_path = OUT_DIR / "live_daily_pnl.json"
        # Exposure state (resets daily)
        self.market_exposure: dict[tuple[str, str], float] = {}  # (cid, our_outcome) -> usd
        self.fades_today = 0
        self.last_signal_ts: dict[tuple[str, str], float] = {}   # (target, cid) -> epoch
        # condition_id -> {"outcomes":[a,b], "tokens":{outcome:token_id}}
        self.market_cache: dict[str, dict] = {}
        self._load_market_index()
        # Prime dedup with recent tx hashes from CSV so a restart doesn't
        # cause a burst of re-fires from the first poll's 500-trade window.
        self._prime_seen_tx()
        print(f"[fade-bot] mode={'LIVE' if live else 'PAPER'}")
        print(f"[fade-bot] tracking {len(self.target_wallets)} target wallets")
        print(f"[fade-bot] preloaded {len(self.market_cache)} markets from CLOB index")
        print(f"[fade-bot] primed {len(self.seen_tx_set)} tx hashes from history")

    def _prime_seen_tx(self):
        """Pre-populate seen_tx_set from the tail of paper_trades.csv.

        Without this, a bot restart sees an empty dedup set and processes the
        first poll's entire 500-trade window as 'new', potentially firing a
        burst of fades on trades we already logged in a previous run.
        """
        if not self.papertrades_path.exists():
            return
        try:
            from collections import deque as _dq
            tail = _dq(maxlen=SEEN_TX_PRIME_LIMIT)
            with self.papertrades_path.open(encoding="utf-8") as fh:
                reader = _csv.DictReader(fh)
                for row in reader:
                    h = (row.get("tx_hash") or "").strip()
                    if h:
                        tail.append(h)
            for h in tail:
                self.seen_tx_set.add(h)
                self.seen_tx.append(h)
        except Exception as e:
            print(f"[fade-bot] seen_tx prime failed: {e}")

    def _load_market_index(self):
        """Pre-populate market metadata from the local CLOB index parquet."""
        try:
            import pandas as pd
            p = ES_DIR / "clob_esports_markets.parquet"
            if not p.exists():
                return
            df = pd.read_parquet(p, columns=["condition_id", "tokens"])
            for _, row in df.iterrows():
                cid = row["condition_id"]
                outs, toks = [], {}
                try:
                    for t in row["tokens"]:
                        o = t.get("outcome"); tid = t.get("token_id")
                        if o and tid:
                            outs.append(o); toks[o] = tid
                except TypeError:
                    continue
                if len(outs) == 2:
                    self.market_cache[cid] = {"outcomes": outs, "tokens": toks}
        except Exception as e:
            print(f"[fade-bot] market index preload failed: {e}")

    def get_market(self, condition_id: str) -> dict | None:
        """Return {outcomes, tokens} for a conditionId, fetching on miss."""
        if condition_id in self.market_cache:
            return self.market_cache[condition_id]
        try:
            r = self.session.get(
                f"https://clob.polymarket.com/markets/{condition_id}", timeout=6
            )
            if r.status_code != 200:
                return None
            j = r.json()
            outs, toks = [], {}
            for t in j.get("tokens", []) or []:
                o = t.get("outcome"); tid = t.get("token_id")
                if o and tid:
                    outs.append(o); toks[o] = tid
            if len(outs) == 2:
                m = {"outcomes": outs, "tokens": toks}
                self.market_cache[condition_id] = m
                return m
        except Exception as e:
            print(f"[fade-bot] market fetch error {condition_id[:10]}: {e}")
        return None

    FADE_PATH   = ES_DIR / "fade_targets.json"
    FOLLOW_PATH = ES_DIR / "follow_targets.json"
    TARGETS_PATH = FADE_PATH  # back-compat for any external reference

    def _load_wallets(self, path: Path) -> tuple[set[str], float]:
        if not path.exists():
            return set(), 0.0
        d = json.loads(path.read_text(encoding="utf-8"))
        wallets = set(w.lower() for w in (d.get("target_wallets") or []))
        return wallets, path.stat().st_mtime

    def _load_targets(self) -> set[str]:
        """Load fade targets + follow targets. Returns fade set for back-compat."""
        fade, self.fade_mtime = self._load_wallets(self.FADE_PATH)
        self.follow_wallets, self.follow_mtime = self._load_wallets(self.FOLLOW_PATH)
        # Back-compat
        self.targets_mtime = self.fade_mtime
        print(f"[fade-bot] loaded {len(fade)} fade + {len(self.follow_wallets)} follow wallets")
        return fade

    def maybe_reload_daily_pnl(self):
        """Refresh self.daily_pnl from live_daily_pnl.json if updated.

        Written by analysis/evaluate_live.py (every 15 min via scheduled task).
        Only the entry for today's UTC date counts — older snapshots are ignored.
        """
        try:
            if not self.daily_pnl_path.exists():
                return
            cur_mtime = self.daily_pnl_path.stat().st_mtime
        except OSError:
            return
        if cur_mtime <= self.daily_pnl_mtime:
            return
        try:
            d = json.loads(self.daily_pnl_path.read_text(encoding="utf-8"))
            today_str = str(datetime.now(timezone.utc).date())
            if d.get("date") == today_str:
                self.daily_pnl = float(d.get("realized_pnl_usd") or 0.0)
            else:
                # Snapshot is from a previous day — today's realized PnL is 0
                self.daily_pnl = 0.0
            self.daily_pnl_mtime = cur_mtime
        except Exception as e:
            print(f"[fade-bot] daily_pnl reload failed: {e}")

    def maybe_reload_targets(self):
        """Hot-reload fade_targets.json AND follow_targets.json on mtime change.

        Lets refresh-targets task update lists without restarting the bot.
        """
        try:
            fade_mtime = self.FADE_PATH.stat().st_mtime if self.FADE_PATH.exists() else 0
            follow_mtime = self.FOLLOW_PATH.stat().st_mtime if self.FOLLOW_PATH.exists() else 0
        except OSError:
            return

        if fade_mtime > getattr(self, "fade_mtime", 0):
            try:
                wallets, _ = self._load_wallets(self.FADE_PATH)
                added = len(wallets - self.target_wallets)
                removed = len(self.target_wallets - wallets)
                self.target_wallets = wallets
                self.fade_mtime = fade_mtime
                self.targets_mtime = fade_mtime
                print(f"[fade-bot] reloaded {len(wallets)} fade targets "
                      f"(+{added} new, -{removed} dropped)")
                self.write_event({"type": "fade_targets_reloaded",
                                  "count": len(wallets), "added": added, "removed": removed})
            except Exception as e:
                print(f"[fade-bot] fade reload failed: {e}")

        if follow_mtime > getattr(self, "follow_mtime", 0):
            try:
                wallets, _ = self._load_wallets(self.FOLLOW_PATH)
                added = len(wallets - self.follow_wallets)
                removed = len(self.follow_wallets - wallets)
                self.follow_wallets = wallets
                self.follow_mtime = follow_mtime
                print(f"[fade-bot] reloaded {len(wallets)} follow targets "
                      f"(+{added} new, -{removed} dropped)")
                self.write_event({"type": "follow_targets_reloaded",
                                  "count": len(wallets), "added": added, "removed": removed})
            except Exception as e:
                print(f"[fade-bot] follow reload failed: {e}")

    def poll(self):
        """Pull recent trades and filter to target wallets."""
        try:
            r = self.session.get(
                "https://data-api.polymarket.com/trades",
                params={"limit": RECENT_TRADES_LIMIT},
                timeout=8,
            )
            if r.status_code != 200:
                return []
            return r.json()
        except Exception as e:
            print(f"[fade-bot] poll error: {e}")
            return []

    def is_target_game(self, slug: str) -> bool:
        s = (slug or "").lower()
        return any(s.startswith(p) for p in ESPORTS_PREFIXES)

    # Backwards-compat alias (name was CS2-only before)
    is_cs2 = is_target_game

    def write_event(self, ev: dict):
        with self.events_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(ev) + "\n")

    def write_paper_trade(self, trade: dict):
        cols = ["timestamp","strategy","target_wallet","fade_condition","fade_slug",
                "their_side","their_outcome","their_price","their_size",
                "our_side","our_outcome","our_entry","our_bet","our_shares_est",
                "our_token_id","tx_hash"]
        new_file = not self.papertrades_path.exists()
        with self.papertrades_path.open("a", encoding="utf-8", newline="") as fh:
            w = _csv.DictWriter(fh, fieldnames=cols)
            if new_file:
                w.writeheader()
            w.writerow({k: trade.get(k, "") for k in cols})

    def process_trade(self, t: dict):
        tx = t.get("transactionHash") or ""
        if tx in self.seen_tx_set:
            return
        self.seen_tx.append(tx)
        self.seen_tx_set.add(tx)
        if len(self.seen_tx_set) > 10000:
            # Trim
            old = list(self.seen_tx)[:-5000]
            for x in old:
                self.seen_tx_set.discard(x)
            self.seen_tx = deque(list(self.seen_tx)[-5000:], maxlen=10000)

        wallet = (t.get("proxyWallet") or "").lower()
        # Pick strategy by wallet membership. Follow wins if a wallet is both
        # (rare — a winner takes precedence over a loser ranking).
        if wallet in self.follow_wallets:
            strategy = "follow"
        elif wallet in self.target_wallets:
            strategy = "fade"
        else:
            return

        slug = t.get("slug") or t.get("eventSlug") or ""
        if not self.is_target_game(slug):
            return

        # Build fade
        their_side = t.get("side")     # BUY or SELL
        their_outcome = t.get("outcome") # the token they bought / sold
        their_price = float(t.get("price") or 0)
        their_size = float(t.get("size") or 0)
        if their_size < 1 or not (0.05 <= their_price <= 0.95):
            return  # skip dust trades and extreme prices

        # Look up the market's two actual outcomes (team names for esports,
        # Yes/No for binary). Skip if we can't resolve metadata.
        condition_id = t.get("conditionId") or ""
        mkt = self.get_market(condition_id)
        if not mkt or their_outcome not in mkt["outcomes"]:
            self.write_event({"type": "skip_no_market", "cid": condition_id, "outcome": their_outcome, "tx": tx})
            return
        other = [o for o in mkt["outcomes"] if o != their_outcome][0]

        # STRATEGY ROUTING
        # FADE:   we BUY the opposite outcome's token (target loses → we win)
        # FOLLOW: we BUY the same outcome's token at the same price (target wins → we win)
        if strategy == "fade":
            if their_side == "BUY":
                our_outcome = other
            else:
                # target SELL = exiting / shorting their_outcome → fade = buy what they sold
                our_outcome = their_outcome
            our_entry = round(1 - their_price, 4)
        else:  # follow
            if their_side == "BUY":
                our_outcome = their_outcome
                our_entry = round(their_price, 4)
            else:
                # target SELL = exiting their_outcome → follow = buy the other side
                our_outcome = other
                our_entry = round(1 - their_price, 4)
        our_token_id = mkt["tokens"].get(our_outcome)

        bet = LIVE_BET_USD if self.live else PAPER_BET_USD

        # UTC day rollover — reset counters and exposure
        today = datetime.now(timezone.utc).date()
        if today != self.day_started:
            self.day_started = today
            self.daily_pnl = 0
            self.daily_risk_usd = 0.0
            self.market_exposure.clear()
            self.fades_today = 0
            self.last_signal_ts.clear()

        # Daily LOSS cap (LIVE only) — uses realized PnL. Currently dormant
        # because LIVE PnL tracking isn't wired yet (no resolution-watch loop).
        # The RISK cap below is the active hard guard.
        if self.live and self.daily_pnl <= -DAILY_LOSS_CAP:
            self.write_event({"type": "skip_daily_loss_cap", "tx": tx, "daily_pnl": self.daily_pnl})
            return

        # Daily RISK cap (LIVE only) — bounds total $ bet per UTC day.
        # This is what actually fires until realized-PnL tracking exists.
        if self.live and self.daily_risk_usd + bet > DAILY_RISK_CAP_USD:
            self.write_event({"type": "skip_daily_risk_cap", "tx": tx,
                              "spent_today": self.daily_risk_usd, "cap": DAILY_RISK_CAP_USD})
            return

        # Per-day fade count cap (sanity)
        if self.fades_today >= MAX_FADES_PER_DAY:
            self.write_event({"type": "skip_daily_count_cap", "tx": tx})
            return

        # Per-market exposure cap
        exp_key = (condition_id, our_outcome)
        prior = self.market_exposure.get(exp_key, 0.0)
        if prior + bet > MAX_PER_MARKET_USD:
            self.write_event({"type": "skip_market_cap", "cid": condition_id,
                              "our_outcome": our_outcome, "prior": prior, "tx": tx})
            return

        # Per-(target, market) debounce — drop rapid repeats from same target on same market
        debounce_key = (wallet, condition_id)
        now_ts = time.time()
        last = self.last_signal_ts.get(debounce_key, 0.0)
        if now_ts - last < MIN_SECONDS_BETWEEN_SAME_TARGET_SAME_MARKET:
            self.write_event({"type": "skip_debounce", "wallet": wallet, "cid": condition_id, "tx": tx})
            return
        self.last_signal_ts[debounce_key] = now_ts

        shares_est = round(bet / max(our_entry, 0.05), 2)

        trade = {
            "timestamp":      t.get("timestamp"),
            "strategy":       strategy,
            "target_wallet":  wallet,
            "fade_condition": t.get("conditionId"),
            "fade_slug":      slug,
            "their_side":     their_side,
            "their_outcome":  their_outcome,
            "their_price":    their_price,
            "their_size":     their_size,
            "our_side":       "BUY",
            "our_outcome":    our_outcome,
            "our_entry":      our_entry,
            "our_bet":        bet,
            "our_shares_est": shares_est,
            "our_token_id":   our_token_id,
            "tx_hash":        tx,
        }

        # Update exposure trackers
        self.market_exposure[exp_key] = prior + bet
        self.fades_today += 1
        if self.live:
            self.daily_risk_usd += bet

        # Paper: log only
        self.write_paper_trade(trade)
        self.write_event({"type": "fade_signal", **trade})
        print(f"[fade-bot] {datetime.utcnow().isoformat(timespec='seconds')}Z  "
              f"{strategy.upper():>6} {wallet[:10]}...  their {their_side} {their_outcome}@{their_price}  "
              f"-> our BUY {our_outcome}@{our_entry}  bet ${bet}  slug={slug[:50]}")

        if self.live:
            self.place_live_order(trade)
        elif self.dry_live:
            # Exercise the same arithmetic without submitting an order.
            price = round(min(MAX_ENTRY_PRICE, trade["our_entry"] + ENTRY_SLIPPAGE), 2)
            shares = round(trade["our_bet"] / max(price, 0.01), 2)
            print(f"[fade-bot]   DRY-LIVE would post BUY {price}x{shares} "
                  f"token={trade.get('our_token_id')}")
            self.write_event({"type": "dry_live_order", "price": price, "shares": shares,
                              "token_id": str(trade.get("our_token_id")),
                              "fade_condition": trade.get("fade_condition"),
                              "our_outcome": trade.get("our_outcome"),
                              "tx": trade.get("tx_hash")})

    def place_live_order(self, trade: dict):
        """Place a GTC BUY on Polymarket CLOB, then poll for fill / cancel on timeout.

        Sequence:
          1. Submit BUY at our_entry + 1c slippage (taker-style).
          2. Poll get_order every LIVE_FILL_POLL_INTERVAL seconds.
          3. If matched → record final fill (price + shares actually matched).
          4. If still resting after LIVE_FILL_TIMEOUT → cancel.
          5. After cancel, re-check status (partial fills count — same defense
             as the 15m bot's v1.10 cancel→open pattern).
        """
        token_id = trade.get("our_token_id")
        if not token_id:
            self.write_event({"type": "live_skip_no_token", "tx": trade.get("tx_hash")})
            return
        price = round(min(MAX_ENTRY_PRICE, trade["our_entry"] + ENTRY_SLIPPAGE), 2)
        if price < MIN_ENTRY_PRICE:
            self.write_event({"type": "live_skip_price_too_low", "price": price, "tx": trade.get("tx_hash")})
            return
        shares = round(trade["our_bet"] / price, 2)

        try:
            from py_clob_client_v2 import OrderArgs, OrderType
            from py_clob_client_v2.order_builder.constants import BUY
            args = OrderArgs(price=price, size=shares, side=BUY, token_id=str(token_id))
            signed = self.client.create_order(args)
            resp = self.client.post_order(signed, OrderType.GTC)
            order_id  = (resp or {}).get("orderID") or (resp or {}).get("orderId") or ""
            init_stat = (resp or {}).get("status", "")
            print(f"[fade-bot]   LIVE order posted: id={order_id} status={init_stat} price={price} shares={shares}")
            self.write_event({"type": "live_order_placed", "order_id": order_id,
                              "status": init_stat, "price": price, "shares": shares,
                              "token_id": str(token_id), "tx": trade.get("tx_hash"),
                              "fade_condition": trade.get("fade_condition"),
                              "our_outcome": trade.get("our_outcome")})
        except Exception as e:
            print(f"[fade-bot]   LIVE order POST FAILED: {e}")
            self.write_event({"type": "live_order_error", "error": str(e),
                              "tx": trade.get("tx_hash")})
            return

        # --- Poll for fill, cancel on timeout ---
        final_status   = init_stat
        final_matched  = 0.0
        final_avg_price = price
        t0 = time.time()
        if order_id:
            while time.time() - t0 < LIVE_FILL_TIMEOUT:
                time.sleep(LIVE_FILL_POLL_INTERVAL)
                try:
                    o = self.client.get_order(order_id) or {}
                    final_status   = str(o.get("status", "")).lower()
                    final_matched  = float(o.get("size_matched") or 0)
                    ap = o.get("average_price")
                    if ap:
                        try:    final_avg_price = float(ap)
                        except (TypeError, ValueError): pass
                except Exception as e:
                    self.write_event({"type": "live_order_status_error",
                                      "order_id": order_id, "error": str(e)})
                    continue
                if final_status == "matched" or final_matched >= shares:
                    break

            # Cancel if still resting at timeout
            if final_status not in ("matched", "cancelled") and final_matched < shares:
                try:
                    self.client.cancel(order_id)
                    # Re-check post-cancel: defends against the cancel-vs-fill race.
                    o2 = self.client.get_order(order_id) or {}
                    final_status  = str(o2.get("status", "")).lower() or "cancelled"
                    new_matched   = float(o2.get("size_matched") or 0)
                    if new_matched > final_matched:
                        final_matched = new_matched
                    ap2 = o2.get("average_price")
                    if ap2:
                        try:    final_avg_price = float(ap2)
                        except (TypeError, ValueError): pass
                    print(f"[fade-bot]   LIVE order CANCELLED id={order_id} matched={final_matched:.2f}/{shares:.2f}")
                except Exception as e:
                    print(f"[fade-bot]   LIVE cancel FAILED id={order_id}: {e}")
                    self.write_event({"type": "live_order_cancel_error",
                                      "order_id": order_id, "error": str(e)})

        cost = round(final_avg_price * final_matched, 4)
        print(f"[fade-bot]   LIVE final: id={order_id} status={final_status} "
              f"matched={final_matched:.2f}@{final_avg_price:.4f} cost=${cost}")
        self.write_event({"type": "live_order_final", "order_id": order_id,
                          "status": final_status, "matched": final_matched,
                          "avg_price": final_avg_price, "cost_usd": cost,
                          "tx": trade.get("tx_hash")})

        # Append to live_orders.jsonl with the FINAL state — evaluate_live.py
        # uses this for PnL. Cost = avg_price * matched (actual $ spent).
        with self.live_orders_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "ts": time.time(),
                "order_id": order_id,
                "status": final_status,
                "price": final_avg_price,
                "shares": final_matched,
                "cost_usd": cost,
                "requested_price": price,
                "requested_shares": shares,
                "token_id": str(token_id),
                **{k: trade.get(k) for k in ("fade_condition", "fade_slug", "our_outcome",
                                              "target_wallet", "strategy")},
            }) + "\n")

    def run(self):
        print(f"[fade-bot] polling every {POLL_INTERVAL}s — writing to {OUT_DIR}")
        last_summary = time.time()
        n_trades_seen = 0
        n_fades = 0
        try:
            while True:
                trades = self.poll()
                for t in trades:
                    n_trades_seen += 1
                    self.process_trade(t)
                # Track fade events from file size
                if self.papertrades_path.exists():
                    n_fades_now = sum(1 for _ in self.papertrades_path.open(encoding="utf-8")) - 1
                else:
                    n_fades_now = 0
                if time.time() - last_summary > 60:
                    pnl_str = f" daily_pnl=${self.daily_pnl:+.2f}" if self.live else ""
                    print(f"[fade-bot] heartbeat: trades_scanned={n_trades_seen} fades={n_fades_now} "
                          f"unique_tx={len(self.seen_tx_set)} targets={len(self.target_wallets)}{pnl_str}")
                    last_summary = time.time()
                    self.maybe_reload_targets()
                    if self.live:
                        self.maybe_reload_daily_pnl()
                time.sleep(POLL_INTERVAL)
        except KeyboardInterrupt:
            print("[fade-bot] stopping")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="Place real orders (blocked by default)")
    ap.add_argument("--dry-live", action="store_true",
                    help="Initialize LIVE client + run all guards, but DON'T submit orders. Pre-flight test mode.")
    args = ap.parse_args()
    if args.live and args.dry_live:
        ap.error("--live and --dry-live are mutually exclusive")
    FadeBot(live=args.live, dry_live=args.dry_live).run()


if __name__ == "__main__":
    main()
