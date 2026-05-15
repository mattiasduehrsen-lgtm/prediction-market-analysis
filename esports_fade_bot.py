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
DAILY_LOSS_CAP = 50.0         # halt for the day if losses exceed this (LIVE)
MAX_PER_MARKET_USD = 10.0     # cumulative bet cap per (market, our_outcome)
MAX_FADES_PER_DAY = 100       # sanity ceiling on daily signal count
MIN_SECONDS_BETWEEN_SAME_TARGET_SAME_MARKET = 30  # debounce rapid repeats
ENTRY_SLIPPAGE = 0.01         # add 1c to our BUY price so order fills (v1.9 pattern)
MIN_ENTRY_PRICE = 0.05        # don't place orders below 5c (no depth)
MAX_ENTRY_PRICE = 0.95        # don't pay >95c (essentially resolved)

# Only consider CS2 (the signal we validated)
ESPORTS_PREFIXES = ("cs2-", "csgo-")


class FadeBot:
    def __init__(self, live: bool = False):
        self.live = live
        self.target_wallets = self._load_targets()
        self.seen_tx = deque(maxlen=10000)  # dedup
        self.seen_tx_set = set()
        self.session = requests.Session()
        self.papertrades_path = OUT_DIR / "paper_trades.csv"
        self.events_path = OUT_DIR / "fade_events.jsonl"
        self.live_orders_path = OUT_DIR / "live_orders.jsonl"
        self.client = None
        if live:
            from src.bot.clob_auth import get_client
            self.client = get_client()
        self.daily_pnl = 0.0
        self.day_started = datetime.now(timezone.utc).date()
        # Exposure state (resets daily)
        self.market_exposure: dict[tuple[str, str], float] = {}  # (cid, our_outcome) -> usd
        self.fades_today = 0
        self.last_signal_ts: dict[tuple[str, str], float] = {}   # (target, cid) -> epoch
        # condition_id -> {"outcomes":[a,b], "tokens":{outcome:token_id}}
        self.market_cache: dict[str, dict] = {}
        self._load_market_index()
        print(f"[fade-bot] mode={'LIVE' if live else 'PAPER'}")
        print(f"[fade-bot] tracking {len(self.target_wallets)} target wallets")
        print(f"[fade-bot] preloaded {len(self.market_cache)} markets from CLOB index")

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

    def _load_targets(self) -> set[str]:
        path = ES_DIR / "fade_targets.json"
        d = json.loads(path.read_text(encoding="utf-8"))
        return set(w.lower() for w in d["target_wallets"])

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

    def is_cs2(self, slug: str) -> bool:
        s = (slug or "").lower()
        return any(s.startswith(p) for p in ESPORTS_PREFIXES)

    def write_event(self, ev: dict):
        with self.events_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(ev) + "\n")

    def write_paper_trade(self, trade: dict):
        cols = ["timestamp","target_wallet","fade_condition","fade_slug",
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
        if wallet not in self.target_wallets:
            return

        slug = t.get("slug") or t.get("eventSlug") or ""
        if not self.is_cs2(slug):
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

        # FADE LOGIC: we BUY the opposite outcome's token.
        #   target BUY X @ p  -> we BUY Y @ (1 - p)
        #   target SELL X @ p (exiting / going short X) -> we BUY X @ (1 - p)
        if their_side == "BUY":
            our_outcome = other
        else:
            our_outcome = their_outcome
        our_token_id = mkt["tokens"].get(our_outcome)
        our_entry = round(1 - their_price, 4)

        bet = LIVE_BET_USD if self.live else PAPER_BET_USD

        # UTC day rollover — reset counters and exposure
        today = datetime.now(timezone.utc).date()
        if today != self.day_started:
            self.day_started = today
            self.daily_pnl = 0
            self.market_exposure.clear()
            self.fades_today = 0
            self.last_signal_ts.clear()

        # Daily loss cap (LIVE only)
        if self.live and self.daily_pnl <= -DAILY_LOSS_CAP:
            self.write_event({"type": "skip_daily_loss_cap", "tx": tx, "daily_pnl": self.daily_pnl})
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

        # Paper: log only
        self.write_paper_trade(trade)
        self.write_event({"type": "fade_signal", **trade})
        print(f"[fade-bot] {datetime.utcnow().isoformat(timespec='seconds')}Z  "
              f"FADE {wallet[:10]}...  their {their_side} {their_outcome}@{their_price}  "
              f"-> our BUY {our_outcome}@{our_entry}  bet ${bet}  slug={slug[:50]}")

        if self.live:
            self.place_live_order(trade)

    def place_live_order(self, trade: dict):
        """Place a GTC BUY on Polymarket CLOB for the fade signal."""
        token_id = trade.get("our_token_id")
        if not token_id:
            self.write_event({"type": "live_skip_no_token", "tx": trade.get("tx_hash")})
            return
        # Add slippage so the order fills as a taker
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
            order_id = (resp or {}).get("orderID") or (resp or {}).get("orderId") or ""
            status = (resp or {}).get("status", "")
            print(f"[fade-bot]   LIVE order posted: id={order_id} status={status} price={price} shares={shares}")
            self.write_event({"type": "live_order_placed", "order_id": order_id,
                              "status": status, "price": price, "shares": shares,
                              "token_id": str(token_id), "tx": trade.get("tx_hash"),
                              "fade_condition": trade.get("fade_condition"),
                              "our_outcome": trade.get("our_outcome")})
            with self.live_orders_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"ts": time.time(), "order_id": order_id,
                                     "status": status, "price": price, "shares": shares,
                                     "token_id": str(token_id),
                                     **{k: trade.get(k) for k in ("fade_condition","fade_slug","our_outcome","target_wallet")}
                                     }) + "\n")
        except Exception as e:
            print(f"[fade-bot]   LIVE order FAILED: {e}")
            self.write_event({"type": "live_order_error", "error": str(e),
                              "tx": trade.get("tx_hash")})

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
                    print(f"[fade-bot] heartbeat: trades_scanned={n_trades_seen} fades={n_fades_now} "
                          f"unique_tx={len(self.seen_tx_set)}")
                    last_summary = time.time()
                time.sleep(POLL_INTERVAL)
        except KeyboardInterrupt:
            print("[fade-bot] stopping")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="Place real orders (blocked by default)")
    args = ap.parse_args()
    FadeBot(live=args.live).run()


if __name__ == "__main__":
    main()
