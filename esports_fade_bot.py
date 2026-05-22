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

try:
    from notify import notify
except Exception:
    def notify(*a, **kw): return False  # graceful fallback if notify import fails

import requests
from dotenv import load_dotenv
load_dotenv()

ROOT = Path(__file__).resolve().parent
ES_DIR = ROOT / "cowork_snapshot" / "esports"
OUT_DIR = ROOT / "output" / "esports_fade"
OUT_DIR.mkdir(parents=True, exist_ok=True)

POLL_INTERVAL = 1.0           # seconds between API polls (was 2.0 — halved 2026-05-20 for latency)
RECENT_TRADES_LIMIT = 500     # how many recent trades to scan each poll
MAX_TRADE_AGE_SECONDS = 300   # skip trades older than this. Raised from 180 to 300
                              # on 2026-05-21 because Polymarket's data-api routinely
                              # lags 180-200s, and we were rejecting trades at exactly
                              # 182-185s (right at the threshold). Latency report
                              # showed p90 matched-lag = 305s, so 300s catches almost
                              # all legitimate signals while still blocking the 5+
                              # min phantom-lag from indexer outages.
PAPER_BET_USD = 5.0           # bet size (PAPER) — kept at $5 for backtest continuity
LIVE_BET_USD = 10.0           # bet size (LIVE) — raised from $5 (2026-05-19) for first scaling step
DAILY_LOSS_CAP = 150.0        # primary stop: halt if today's REALIZED losses
                              # exceed this $ amount (LIVE; uses live_daily_pnl.json
                              # which the eval_live cron refreshes every 10 min).
                              # Replaces the older immediate-risk cap so we can
                              # keep trading on winning days regardless of $ deployed.
DAILY_RISK_CAP_USD = 2000.0   # SAFETY BACKSTOP only — halts if we've placed $2000
                              # in matched orders today. Should never fire unless
                              # realized-PnL tracking breaks (cron stops, file corrupt,
                              # etc). Raised from $500 to $2000 on 2026-05-20 so the
                              # cap stops being binding during high-activity days.
                              # At $10/trade this caps at 200 fills/day.
MAX_PER_MARKET_USD = 50.0     # cumulative bet cap per (market, our_outcome) — raised from $25 (2026-05-19) to preserve 5-fill stacking at $10 bet size
MAX_FADES_PER_DAY = 500       # sanity ceiling on daily signal count — raised from 100 (2026-05-18)
MIN_SECONDS_BETWEEN_SAME_TARGET_SAME_MARKET = 30  # debounce rapid repeats
ENTRY_SLIPPAGE = 0.01         # add 1c to our BUY price so order fills (v1.9 pattern)
MIN_ENTRY_PRICE = 0.05        # don't place orders below 5c (no depth)
MAX_ENTRY_PRICE = 0.95        # don't pay >95c (essentially resolved)
# LIVE-only quality filter. Live data through 2026-05-18 showed 0/5 WR at
# our_entry in [0.20, 0.40), vs 67-91% WR at [0.40, 0.80]. The 20-40c bucket
# is where the fade is most often "right, but the market knows" — target is
# selling into bad news, we're catching the falling knife at a price the
# crowd has already moved past. Cut it on LIVE only; PAPER keeps collecting
# so we can keep validating the rule.
LIVE_MIN_OUR_ENTRY = 0.40
SEEN_TX_PRIME_LIMIT = 2000    # how many recent tx hashes to load from CSV on startup
LIVE_FILL_POLL_INTERVAL = 0.5 # seconds between fill checks (was 2.0 — quartered 2026-05-20 for latency)
LIVE_FILL_TIMEOUT = 12.0      # cancel if not matched within this many seconds
# Take-profit sweep: DISABLED by default.
# At a threshold like 0.95 the EV of selling = 0.95 = EV of holding (0.95 * 1),
# but selling gives up the last ~5c × shares when markets resolve fully in our
# favor (which happens often on CS2 series-winners). The +110% live example
# confirmed this: holding to resolution beat selling at TP.
# Set TP_MIN_PRICE < 1.0 to re-enable. Useful if we ever start hitting the
# daily risk cap and need to free capital sooner.
TP_MIN_PRICE = 2.0            # 2.0 = disabled (no bid can exceed 1.0)
TP_SELL_CAP_CENTS = 99
TP_SWEEP_INTERVAL = 60.0

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

    def refresh_daily_risk(self) -> None:
        """Recompute today's daily_risk_usd from actual matched BUYs.

        Sums cost_usd of all matched BUY orders in live_orders.jsonl since the
        most recent UTC midnight. Source-of-truth approach: errors and cancels
        no longer inflate the counter. Called from the heartbeat loop.
        """
        try:
            today = datetime.now(timezone.utc).date()
            midnight = datetime(today.year, today.month, today.day,
                                tzinfo=timezone.utc).timestamp()
            total = 0.0
            if self.live_orders_path.exists():
                with self.live_orders_path.open(encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            o = json.loads(line)
                        except Exception:
                            continue
                        if str(o.get("side", "BUY")).upper() != "BUY":
                            continue
                        if str(o.get("status", "")).lower() != "matched":
                            continue
                        if (o.get("ts") or 0) < midnight:
                            continue
                        try:
                            total += float(o.get("cost_usd") or 0)
                        except (TypeError, ValueError):
                            pass
            self.daily_risk_usd = round(total, 2)
        except Exception as e:
            print(f"[fade-bot] daily_risk refresh failed: {e}")

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
        # Auto-add a wall-clock timestamp to every event so downstream tools
        # can filter by time. Doesn't overwrite an existing `ts` field —
        # callers that already supplied one (e.g. live_order_final) keep theirs.
        if "ts" not in ev:
            ev["ts"] = time.time()
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
        # LATENCY INSTRUMENTATION: capture the wall-clock time we first saw
        # this trade. Used by analysis/latency_report.py to measure how stale
        # our view of the world was when we acted.
        signal_seen_at = time.time()
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

        # GLOBAL STALE COUNTER (cheap, no events) — used by the heartbeat
        # stall detector to recognize Polymarket-indexer-lag situations
        # (high stale rate = their indexer is behind, not our problem).
        try:
            their_fill_ts = float(t.get("timestamp") or 0)
        except (TypeError, ValueError):
            their_fill_ts = 0
        if their_fill_ts > 0 and (signal_seen_at - their_fill_ts) > MAX_TRADE_AGE_SECONDS:
            self.stale_trades_skipped = getattr(self, "stale_trades_skipped", 0) + 1
            is_stale = True
        else:
            is_stale = False

        # WALLET CHECK — if not a target/follower, exit immediately. This is
        # cheap (O(1) set lookup) and saves work for the 99.9%+ of trades that
        # aren't from wallets we care about.
        wallet = (t.get("proxyWallet") or "").lower()
        if wallet in self.follow_wallets:
            strategy = "follow"
        elif wallet in self.target_wallets:
            strategy = "fade"
        else:
            return

        # TARGET-WALLET STALE FILTER: only fires when the trade IS from a
        # target wallet AND is stale. These events are diagnostic gold —
        # every one represents a real signal we missed due to indexer lag.
        if is_stale:
            age = signal_seen_at - their_fill_ts
            self.target_stale_skips = getattr(self, "target_stale_skips", 0) + 1
            self.write_event({"type": "skip_stale_target_trade", "tx": tx,
                              "wallet": wallet, "strategy": strategy,
                              "age_s": round(age, 1),
                              "target_skip_count": self.target_stale_skips})
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

        # Daily LOSS cap (LIVE only) — PRIMARY stop. Halts new entries once
        # today's realized losses pass DAILY_LOSS_CAP. daily_pnl is refreshed
        # from live_daily_pnl.json (eval_live cron, every 10 min) so this lags
        # the on-chain truth by up to ~10 min — acceptable for a stop-loss.
        # Telegram-triggered pause flag — set by /pause command. Stops new
        # entries (LIVE only); existing positions remain.
        if self.live and (OUT_DIR / "paused.flag").exists():
            self.write_event({"type": "skip_paused", "tx": tx})
            return

        if self.live and self.daily_pnl <= -DAILY_LOSS_CAP:
            self.write_event({"type": "skip_daily_loss_cap", "tx": tx,
                              "daily_pnl": self.daily_pnl, "cap": DAILY_LOSS_CAP})
            notify(
                f"🛑 <b>Daily loss cap hit</b>\n"
                f"Today's realized PnL: ${self.daily_pnl:+.2f}\n"
                f"Cap: -${DAILY_LOSS_CAP:.0f}. Bot will stop placing new orders today.\n"
                f"Open positions remain.",
                kind="loss_cap", cooldown=86400,  # 24h — only once per day
            )
            return

        # Daily RISK cap (LIVE only) — SAFETY BACKSTOP. Only fires if we've
        # somehow placed $500+ in orders without the loss-PnL feed catching up.
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
            # LATENCY INSTRUMENTATION:
            "their_fill_ts":   float(t.get("timestamp") or 0),
            "signal_seen_at":  signal_seen_at,
            "signal_lag_s":    round(signal_seen_at - float(t.get("timestamp") or signal_seen_at), 3),
        }

        # Update exposure trackers (paper-side counters always; live-risk only
        # when we'll actually place an order — see entry-price filter below)
        self.market_exposure[exp_key] = prior + bet
        self.fades_today += 1

        # Paper trade log: only write when running in actual PAPER mode.
        # In LIVE mode (current operation), paper_trades.csv is just
        # duplicate data — fade_events.jsonl has the same info. Skip the
        # write to save IO. (2026-05-21 — per user: stop using compute
        # power on paper-trading side-effects, focus on LIVE.)
        if not self.live:
            self.write_paper_trade(trade)
        self.write_event({"type": "fade_signal", **trade})
        # Heartbeat fades counter (used by stall detector). Used to count
        # paper_trades.csv lines but now reads in-memory since we skip the
        # CSV write in LIVE mode.
        self.fade_signals_count = getattr(self, "fade_signals_count", 0) + 1
        print(f"[fade-bot] {datetime.utcnow().isoformat(timespec='seconds')}Z  "
              f"{strategy.upper():>6} {wallet[:10]}...  their {their_side} {their_outcome}@{their_price}  "
              f"-> our BUY {our_outcome}@{our_entry}  bet ${bet}  slug={slug[:50]}")

        if self.live:
            # LIVE-only entry-price floor. Live data through 2026-05-18 showed
            # 0/5 WR at our_entry in [0.20, 0.40). Skip BEFORE bumping the
            # daily-risk counter so a screened signal doesn't eat into the cap.
            if our_entry < LIVE_MIN_OUR_ENTRY:
                self.write_event({"type": "skip_entry_price_floor", "tx": tx,
                                  "our_entry": our_entry, "floor": LIVE_MIN_OUR_ENTRY,
                                  "strategy": strategy, "slug": slug})
                return
            # NOTE: daily_risk_usd is now tracked by _refresh_daily_risk()
            # (called from heartbeat). It sums actual matched BUYs from
            # live_orders.jsonl since UTC midnight, so errors and cancels
            # don't inflate the counter. Don't increment here.
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

        # LATENCY INSTRUMENTATION: time the signing + submission round-trip.
        signal_seen_at = float(trade.get("signal_seen_at") or 0)
        their_fill_ts  = float(trade.get("their_fill_ts") or 0)
        submit_at = time.time()
        try:
            from py_clob_client_v2 import OrderArgs, OrderType
            from py_clob_client_v2.order_builder.constants import BUY
            args = OrderArgs(price=price, size=shares, side=BUY, token_id=str(token_id))
            signed = self.client.create_order(args)
            sign_at = time.time()
            resp = self.client.post_order(signed, OrderType.GTC)
            response_at = time.time()
            order_id  = (resp or {}).get("orderID") or (resp or {}).get("orderId") or ""
            init_stat = (resp or {}).get("status", "")
            print(f"[fade-bot]   LIVE order posted: id={order_id} status={init_stat} price={price} shares={shares}")
            self.write_event({"type": "live_order_placed", "order_id": order_id,
                              "status": init_stat, "price": price, "shares": shares,
                              "token_id": str(token_id), "tx": trade.get("tx_hash"),
                              "fade_condition": trade.get("fade_condition"),
                              "our_outcome": trade.get("our_outcome"),
                              # Latency breakdown (all in seconds):
                              "their_fill_ts":   their_fill_ts,
                              "signal_seen_at":  signal_seen_at,
                              "submit_at":       submit_at,
                              "sign_at":         sign_at,
                              "response_at":     response_at,
                              "lag_signal_to_submit_s": round(submit_at - signal_seen_at, 3) if signal_seen_at else None,
                              "lag_sign_s":            round(sign_at - submit_at, 3),
                              "lag_post_s":            round(response_at - sign_at, 3),
                              "lag_their_fill_to_submit_s": round(submit_at - their_fill_ts, 3) if their_fill_ts else None,
                              })
        except Exception as e:
            response_at = time.time()
            err_str = str(e)
            print(f"[fade-bot]   LIVE order POST FAILED: {e}")
            self.write_event({"type": "live_order_error", "error": err_str,
                              "tx": trade.get("tx_hash"),
                              "their_fill_ts": their_fill_ts,
                              "signal_seen_at": signal_seen_at,
                              "submit_at": submit_at,
                              "response_at": response_at,
                              "lag_to_failure_s": round(response_at - their_fill_ts, 3) if their_fill_ts else None})
            # Telegram alert — surface balance issues immediately, group other errors.
            if "not enough balance" in err_str.lower() or "insufficient" in err_str.lower():
                notify(
                    f"💸 <b>Bot out of pUSD</b>\n"
                    f"Order failed — insufficient balance.\n"
                    f"Top up the proxy wallet to keep trading.",
                    kind="balance_low", cooldown=21600,  # 6h
                )
            else:
                notify(
                    f"❌ <b>Order error</b>\n<code>{err_str[:200]}</code>",
                    kind="order_error", cooldown=1800,  # 30m
                )
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
                    # cancel_orders (plural) takes a list of order_id strings;
                    # cancel_order (singular) needs an OrderPayload wrapper
                    self.client.cancel_orders([order_id])
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

        final_at = time.time()
        cost = round(final_avg_price * final_matched, 4)
        print(f"[fade-bot]   LIVE final: id={order_id} status={final_status} "
              f"matched={final_matched:.2f}@{final_avg_price:.4f} cost=${cost}")
        self.write_event({"type": "live_order_final", "order_id": order_id,
                          "status": final_status, "matched": final_matched,
                          "avg_price": final_avg_price, "cost_usd": cost,
                          "tx": trade.get("tx_hash"),
                          # Latency breakdown (final state):
                          "their_fill_ts":  their_fill_ts,
                          "signal_seen_at": signal_seen_at,
                          "submit_at":      submit_at,
                          "response_at":    response_at,
                          "final_at":       final_at,
                          "lag_total_s":           round(final_at - their_fill_ts, 3) if their_fill_ts else None,
                          "lag_signal_to_final_s": round(final_at - signal_seen_at, 3) if signal_seen_at else None,
                          "lag_submit_to_final_s": round(final_at - response_at, 3)})

        # Append to live_orders.jsonl with the FINAL state — evaluate_live.py
        # uses this for PnL. Cost = avg_price * matched (actual $ spent).
        with self.live_orders_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "ts": time.time(),
                "side": "BUY",
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

    def take_profit_sweep(self):
        """SELL any open CTF positions where the current best bid >= TP_MIN_PRICE.

        Runs every TP_SWEEP_INTERVAL seconds from the bot's heartbeat. Only fires
        in LIVE mode (paper has no real positions). Quietly skips if no client.
        """
        if not self.client:
            return
        try:
            import requests as _r
            proxy = (self.client.get_address() if hasattr(self.client, "get_address") else "")
            if not proxy:
                import os as _os
                proxy = _os.environ.get("POLYMARKET_PROXY_ADDRESS", "").strip()
            r = _r.get("https://data-api.polymarket.com/positions",
                       params={"user": proxy, "limit": 200}, timeout=8)
            if r.status_code != 200:
                return
            positions = r.json() or []
        except Exception as e:
            print(f"[fade-bot] tp_sweep positions fetch failed: {e}")
            return

        open_positions = [p for p in positions
                          if float(p.get("size") or 0) > 0.01 and not p.get("redeemable")]
        if not open_positions:
            return

        try:
            from py_clob_client_v2 import OrderArgs, OrderType
            from py_clob_client_v2.order_builder.constants import SELL
        except Exception:
            return

        for p in open_positions:
            tid = p.get("asset") or p.get("token_id", "")
            if not tid:
                continue
            size = float(p.get("size") or 0)
            try:
                ob = self.client.get_order_book(str(tid)) or {}
                bids = ob.get("bids") if isinstance(ob, dict) else []
                if not bids:
                    continue
                last = bids[-1]
                best_bid = float(last.get("price") if isinstance(last, dict) else getattr(last, "price", 0))
            except Exception:
                continue
            if best_bid < TP_MIN_PRICE:
                continue
            # Avoid re-selling — skip if we already have an open SELL for this token.
            if str(tid) in getattr(self, "tp_sells_placed", set()):
                continue

            sell_price = round(min(TP_SELL_CAP_CENTS / 100.0, best_bid), 2)
            sell_size  = round(size, 2)
            if sell_size < 1:    # skip dust
                continue
            try:
                args_o = OrderArgs(price=sell_price, size=sell_size, side=SELL, token_id=str(tid))
                signed = self.client.create_order(args_o)
                resp = self.client.post_order(signed, OrderType.GTC)
                oid = (resp or {}).get("orderID") or (resp or {}).get("orderId") or ""
                status = (resp or {}).get("status", "")
                outcome = p.get("outcome", "?")
                print(f"[fade-bot]   TP SELL {sell_size}@{sell_price} {outcome[:18]:>18}  id={oid[:18]}... status={status}")
                if not hasattr(self, "tp_sells_placed"):
                    self.tp_sells_placed = set()
                self.tp_sells_placed.add(str(tid))
                self.write_event({"type": "tp_sell_placed", "order_id": oid, "status": status,
                                  "price": sell_price, "shares": sell_size,
                                  "token_id": str(tid), "outcome": outcome})
                # Log to live_orders.jsonl so evaluate_live.py can match BUY+SELL
                # pairs and compute realized PnL = proceeds - cost.
                with self.live_orders_path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps({
                        "ts": time.time(),
                        "side": "SELL",
                        "order_id": oid,
                        "status": status,
                        "price": sell_price,
                        "shares": sell_size,
                        "cost_usd": round(sell_price * sell_size, 4),  # for SELLs this is PROCEEDS
                        "token_id": str(tid),
                        "fade_condition": p.get("conditionId") or "",
                        "fade_slug": p.get("slug") or "",
                        "our_outcome": outcome,
                        "tp_reason": "auto_sweep",
                    }) + "\n")
            except Exception as e:
                print(f"[fade-bot]   TP SELL FAILED for {p.get('outcome','?')}: {e}")

    def run(self):
        print(f"[fade-bot] polling every {POLL_INTERVAL}s — writing to {OUT_DIR}")
        # Initialize daily_risk_usd from actual matched orders today
        if self.live:
            self.refresh_daily_risk()
            print(f"[fade-bot] daily_risk_usd initialized: ${self.daily_risk_usd:.2f}")
        # Startup ping — useful to confirm restarts happened. Cooldown=0 so we
        # always see startup events, but limit to once per 5 min to dedupe a
        # tight watchdog restart loop.
        notify(
            f"🟢 <b>Bot started</b>\nmode={'LIVE' if self.live else 'PAPER'}\n"
            f"targets={len(self.target_wallets)}",
            kind="startup", cooldown=300,
        )
        last_summary = time.time()
        last_tp_sweep = 0.0  # fire immediately on first heartbeat
        n_trades_seen = 0
        n_fades = 0
        self.tp_sells_placed = set()
        # Signal-stall detection state. We flag when `fades` stays flat for
        # >SIGNAL_STALL_SECONDS while `trades_scanned` continues to grow —
        # signature of "bot healthy, world dead" (e.g. data-api content drought
        # after a Polymarket maintenance, or a tournament-schedule lull).
        SIGNAL_STALL_SECONDS = 7200  # 2 hours
        last_fades_value = 0
        last_fades_change_at = time.time()
        last_scans_at_change = 0
        stall_active = False
        stall_flag_path = OUT_DIR / "signal_stall.flag"
        try:
            while True:
                trades = self.poll()
                for t in trades:
                    n_trades_seen += 1
                    self.process_trade(t)
                # In-memory fade-signal counter (was: line count of
                # paper_trades.csv, which is no longer written in LIVE mode).
                # Backfill from the CSV ONLY on first heartbeat so the counter
                # starts at the right baseline across restarts.
                if not hasattr(self, "fade_signals_count"):
                    if self.papertrades_path.exists():
                        baseline = sum(1 for _ in self.papertrades_path.open(encoding="utf-8")) - 1
                        self.fade_signals_count = max(0, baseline)
                    else:
                        self.fade_signals_count = 0
                n_fades_now = self.fade_signals_count
                if time.time() - last_summary > 60:
                    pnl_str = f" daily_pnl=${self.daily_pnl:+.2f}" if self.live else ""
                    print(f"[fade-bot] heartbeat: trades_scanned={n_trades_seen} fades={n_fades_now} "
                          f"unique_tx={len(self.seen_tx_set)} targets={len(self.target_wallets)}{pnl_str}")

                    # ── Signal-stall detection ─────────────────────────────
                    now = time.time()
                    if n_fades_now > last_fades_value:
                        # Fades counter advanced — clear any active stall
                        if stall_active:
                            stall_duration = round(now - last_fades_change_at, 0)
                            print(f"[fade-bot] STALL RECOVERED after {stall_duration:.0f}s "
                                  f"({stall_duration/3600:.1f}h) — fades resumed")
                            self.write_event({
                                "type": "signal_stall_recovered",
                                "ts": now,
                                "stall_seconds": stall_duration,
                                "fades_now": n_fades_now,
                                "trades_scanned": n_trades_seen,
                            })
                            notify(
                                f"✅ <b>Signals resumed</b>\n"
                                f"Stall ended after {stall_duration/3600:.1f}h. Bot is trading again.",
                                kind="signal_stall_recovered", cooldown=0,
                            )
                            try: stall_flag_path.unlink()
                            except FileNotFoundError: pass
                            stall_active = False
                        last_fades_value = n_fades_now
                        last_fades_change_at = now
                        last_scans_at_change = n_trades_seen
                    else:
                        # Fades flat. Check if we've crossed the stall threshold AND
                        # the bot is still polling (trades_scanned growing).
                        flat_seconds = now - last_fades_change_at
                        scans_since_change = n_trades_seen - last_scans_at_change
                        if (not stall_active
                                and flat_seconds > SIGNAL_STALL_SECONDS
                                and scans_since_change > 0):
                            print(f"[fade-bot] !!! SIGNAL STALL DETECTED !!! "
                                  f"fades stuck at {n_fades_now} for {flat_seconds/3600:.1f}h "
                                  f"while {scans_since_change:,} trades scanned. "
                                  f"Bot healthy but no target-wallet activity.")
                            self.write_event({
                                "type": "signal_stall_detected",
                                "ts": now,
                                "stall_seconds": round(flat_seconds, 0),
                                "fades": n_fades_now,
                                "trades_scanned_during_stall": scans_since_change,
                            })
                            # Diagnose: high stale-skip rate suggests Polymarket
                            # indexer lag rather than genuine market drought.
                            stale_count = getattr(self, "stale_trades_skipped", 0)
                            likely_indexer_lag = stale_count > 1000  # >1000 stale skips during stall
                            cause = ("Polymarket data-api is serving stale trades "
                                     "(indexer lag) — restart won't help, wait it out"
                                    if likely_indexer_lag else
                                     "NA daytime drought or tournament gap — wait for matches")
                            notify(
                                f"⚠️ <b>Signal stall</b>\n"
                                f"No fade signals for {flat_seconds/3600:.1f}h.\n"
                                f"Bot is polling fine ({scans_since_change:,} trades scanned), "
                                f"but no target wallets traded.\n\n"
                                f"<b>Likely cause:</b> {cause}.\n"
                                f"Run /diagnose for details.",
                                kind="signal_stall", cooldown=14400,  # 4h — don't re-alert until recovery
                            )
                            try:
                                stall_flag_path.write_text(json.dumps({
                                    "stall_started_at": last_fades_change_at,
                                    "fades_at_stall":   n_fades_now,
                                    "detected_at":      now,
                                    "stall_seconds":    round(flat_seconds, 0),
                                }), encoding="utf-8")
                            except Exception:
                                pass
                            stall_active = True
                    # ───────────────────────────────────────────────────────

                    last_summary = now
                    self.maybe_reload_targets()
                    if self.live:
                        self.maybe_reload_daily_pnl()
                        self.refresh_daily_risk()
                        if time.time() - last_tp_sweep >= TP_SWEEP_INTERVAL:
                            self.take_profit_sweep()
                            last_tp_sweep = time.time()
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
