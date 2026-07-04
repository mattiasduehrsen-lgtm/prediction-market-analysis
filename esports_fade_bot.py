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
import os
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
FOLLOW_ENABLED = False        # FOLLOW strategy disabled 2026-05-21 at n=25 (-9.4% ROI).
                              # Bot still loads follow_wallets so the data path stays
                              # warm — only the strategy routing is bypassed. Set to
                              # True to re-enable once the strategy is refined.
MAX_TRADE_AGE_SECONDS = 300   # skip trades older than this. Raised from 180 to 300
                              # on 2026-05-21 because Polymarket's data-api routinely
                              # lags 180-200s, and we were rejecting trades at exactly
                              # 182-185s (right at the threshold). Latency report
                              # showed p90 matched-lag = 305s, so 300s catches almost
                              # all legitimate signals while still blocking the 5+
                              # min phantom-lag from indexer outages.
PAPER_BET_USD = 5.0           # bet size (PAPER) — kept at $5 for backtest continuity
LIVE_BET_USD = 15.0           # bet size (LIVE) — raised $10 → $15 (2026-05-24) after
                              # wallet-equity reconcile showed +$214 / +28.6% ROI over
                              # 9 days on $749 starting deposit. Sample 275 trades.
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
MAX_FADES_PER_WALLET_PER_DAY = 3  # v1.39 — cap fades per target wallet per UTC day.
                              # Diagnostic on 415 live trades (2026-05-29) found wallet
                              # 0x47138dc1 was faded 90x (22% of all volume) for -$109,
                              # over half the total loss. It's a hyperactive bot/sharp,
                              # not a persistent loser. No single wallet should dominate.
# ── Elo MODEL FILTER (v1.41) ────────────────────────────────────────────────
# Backtest (2026-06-02): fade+model beats fade-only and model-only. On CS2 series
# markets with target activity, fading ONLY when the Elo model also likes our
# side by >0.10 returned +30% ROI (vs +19% model-only, +10% fade-only) — because
# the fade tells us WHEN the model's edge is real (a loser is on the other side).
# When enabled, a LIVE fade is placed only if the model confirms our side is
# under-priced. CS2/CSGO markets where teams can't be matched, and non-CS2
# markets (LoL — no model), are SKIPPED on LIVE (logged). PAPER is unaffected.
MODEL_FILTER_ENABLED = True
MODEL_FILTER_MIN_EDGE = 0.10   # v1.54 (Ship #1): the validated gate. On feasibility +
                               # OOS + live shadow data, edge>=0.10 = +20.6% @3c friction
                               # (monotonic dose-response). Below it, fades are ~breakeven.
# ── Quarter-Kelly sizing (Ship #4) — DEPLOYED DARK, default OFF ─────────────────
# stake = equity * min(0.25*(q-p)/(1-p), 2.5%), then capped by market-cap headroom
# and 25% of ask-side book depth; floor $1. Replayed on the 393 gated bets:
# $1,000 -> $5,421 vs $2,216 flat — 2.4x growth, never >2.5%/bet. Per the war-room
# rule, do NOT size up an unproven stream: enable (KELLY_ENABLED=1) only after the
# v1.54 gate shows positive ROI on its first ~50 live fills. Until then flat $15.
import os as _os_k
KELLY_ENABLED = _os_k.getenv("KELLY_ENABLED", "0") in ("1", "true", "True")
KELLY_FRACTION = 0.25
KELLY_CAP_PCT = 0.025          # never risk >2.5% of equity on one bet
KELLY_MIN_USD = 1.0
# Shadow A/B (v1.53): log the Cowork esports_model Predictor's call next to the
# live Elo filter on every CS2 fade. PURELY OBSERVATIONAL — never changes a trade.
# Disable with SHADOW_MODEL_ENABLED=0 (env). Trading is unaffected if it fails.
import os as _os_sh
SHADOW_MODEL_ENABLED = _os_sh.getenv("SHADOW_MODEL_ENABLED", "1") not in ("0", "false", "False")
                               # validation. Backtest: fade+model still positive
                               # below 0.10 (thr 0.0 +13.8%, 0.10 +30%), so a
                               # modest loosening trades a bit of per-bet edge for
                               # ~2-3x the volume. Revisit after a real sample.
MODEL_FILTER_GAMES_PREFIXES = ("cs2-", "csgo-")  # games the Elo model covers

SKIP_SINGLE_MAP_MARKETS = True  # v1.39 — skip Bo1 single-map/game markets (slug has
                              # -game / -map-). Live ROI: map/game -8.1% vs series -3.5%.
                              # A single map is a coin flip; the loser-edge dilutes.
MIN_SECONDS_BETWEEN_SAME_TARGET_SAME_MARKET = 30  # debounce rapid repeats
ENTRY_SLIPPAGE = 0.01         # add 1c to our BUY price so order fills (v1.9 pattern)
MIN_ENTRY_PRICE = 0.05        # don't place orders below 5c (no depth)
MAX_ENTRY_PRICE = 0.95        # don't pay >95c (essentially resolved)
# LIVE-only longshot floor. Originally 0.40, from a 0/5 WR sample in [0.20,0.40)
# through 2026-05-18. BUT that sample predates the v1.41 Elo MODEL FILTER, which
# now independently screens every fade for value (only fires when the model says
# our side is underpriced by > MODEL_FILTER_MIN_EDGE). With the model filter live,
# 0.40 was redundantly blocking the strategy's strongest setups: in 48h (2026-06-18)
# ALL 10 model-APPROVED fades were killed by the 0.40 floor (underdog buys at
# 0.25-0.39). Lowered to 0.20 (2026-06-18, v1.47): trust the model filter for the
# 0.20-0.40 band, keep a floor only against extreme sub-0.20 longshots (favorite
# almost always wins, liquidity/resolution risk high). Daily loss + risk caps still
# bound downside. Revisit if model-approved sub-0.40 fades underperform on LIVE.
# v1.54 (Ship #1): lowered 0.20 -> 0.10. The war-room analysis proved the entry-price
# floor was blocking exactly where the edge lives: model-CONFIRMED low-price entries
# (<=0.35) were the ONLY profitable fills (+17.8%). Blind underdog fades lose; but a
# 0.10-priced underdog that the v2 model also likes by >=0.10 is the best segment, not
# the worst. The model-edge gate now does the quality control the floor used to fake.
LIVE_MIN_OUR_ENTRY = 0.10
SEEN_TX_PRIME_LIMIT = 2000    # how many recent tx hashes to load from CSV on startup
LIVE_FILL_POLL_INTERVAL = 0.5 # seconds between fill checks (was 2.0 — quartered 2026-05-20 for latency)
LIVE_FILL_TIMEOUT = 12.0      # taker: cancel if not matched within this many seconds
# ── Maker-first execution (Ship #3, 2026-07-02) ────────────────────────────────
# Mean fill cost measured at ~1.7c/fill (533 fills) ≈ most of the raw edge. Post
# GTC AT the signal price (no +1c) unless the model edge is big enough to justify
# paying the spread. Maker orders wait longer, then cancel — never chase.
# Monitor: exec_mode is tagged on live_order events + live_orders.jsonl; compare
# maker-fill WR vs taker-fill WR after ~100 fills (adverse-selection check).
MAKER_FIRST_ENABLED = os.getenv("MAKER_FIRST_ENABLED", "1") not in ("0", "false", "False")
MAKER_TAKER_EDGE = 0.15       # edge >= this -> pay up (taker), the edge covers it
MAKER_FILL_TIMEOUT = 90.0     # maker rest time before cancel (books are slow pre-match)
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
ESPORTS_PREFIXES = ("cs2-", "csgo-", "league-", "lol-", "arch-lol-")
# LoL WENT LIVE 2026-07-01 (v1.55) after both pre-registered go-live gates passed on
# 155 observe-only samples: median book depth $318 (71% fillable at bet size) and
# would_fade=28 (real edge exists at the threshold). LoL fades route through the SAME
# v1.54 model-edge gate (v2 LoL model primary, edge>=0.10, Elo fallback) + a book-depth
# guard. The observe stream STILL logs every LoL signal (feeds backtest_lol.py) —
# setting this back to True reverts LoL to observe-only (the kill switch).
LOL_OBSERVE_ONLY = os.getenv("LOL_OBSERVE_ONLY", "0") in ("1", "true", "True")
LOL_PREFIXES = ("lol-", "arch-lol-", "league-")

# On-chain real-time signal source (v1.40). The data-api /trades feed is ~220s
# stale; the Polygon chain tip is ~2s. We watch ERC-1155 TransferSingle events
# on the Conditional Tokens contract filtered to our target wallets, decode them
# into the same trade shape the data-api produces, and run them through the SAME
# process_trade pipeline (all safety gates apply). The data-api poll stays on as
# a backstop; whichever source sees a tx first wins (deduped by tx hash).
ONCHAIN_ENABLED = True

# On-chain CU gate: only run the eth_getLogs polling while a CS2 match window is
# open. Most of the day has no live CS2 -> idling the listener then is the bulk of
# the Alchemy CU savings (v1.46). Windows are built from clob_esports_markets.parquet
# (a real match has a populated game_start; prop/futures markets don't). Buffers are
# generous so we never miss pre-match or long Bo5s; the data-api poll backstops any
# window we misjudge. Disable via ONCHAIN_GATE_ENABLED=0.
ONCHAIN_GATE_ENABLED = os.getenv("ONCHAIN_GATE_ENABLED", "1") not in ("0", "false", "False")
CS2_WINDOW_PRE_S = 2 * 3600      # start polling 2h before scheduled match start
CS2_WINDOW_POST_S = 5 * 3600     # keep polling 5h after start (covers long Bo5 + delays)
CS2_WINDOW_REFRESH_S = 300       # rebuild the window list from the parquet at most this often

# Matches every NON-series-moneyline market: per-map/per-game winners, handicaps,
# totals, kills, first-blood/tower. We trade series moneylines ONLY — the model
# prices P(win the series); on any other market that probability is meaningless.
# v1.58 FIX: GRID's new LoL slugs use "-game-handicap" (no digit), which the old
# regex (-game\d) MISSED — the bot placed real orders on handicap markets with
# fictitious "edges" (series prob vs handicap price), e.g. lol-hle1-g2-...-game-
# handicap filled $15 @0.34 on a fake +0.16 edge. Regex now catches all prop forms.
import re as _re
_SINGLE_MAP_RE = _re.compile(
    r"-game\d+|-game-|-map-?\d*\b|-map-|handicap|kill-over|kill-under|first-blood"
    r"|first-tower|total-|-total\b|over-under|round-total", _re.IGNORECASE)


def is_single_map_market(slug: str) -> bool:
    return bool(_SINGLE_MAP_RE.search(slug or ""))


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
        # Exposure state — TRACKS POSITIONS HELD across days/restarts (NOT daily volume).
        # (cid, our_outcome) -> usd cost of net-open (unsold) shares. Used by:
        #   1. Per-market position cap (don't accumulate too much on one market)
        #   2. Opposite-side hedge guard (don't buy both sides of binary market)
        # Rebuilt from live_orders.jsonl on startup so restarts don't lose state.
        self.market_exposure: dict[tuple[str, str], float] = {}  # (cid, our_outcome) -> usd
        self.fades_today = 0
        self.fades_by_wallet_today: dict[str, int] = {}          # wallet -> fade count (resets UTC daily)
        self.last_signal_ts: dict[tuple[str, str], float] = {}   # (target, cid) -> epoch
        # condition_id -> {"outcomes":[a,b], "tokens":{outcome:token_id}}
        self.market_cache: dict[str, dict] = {}
        self._load_market_index()
        # Prime dedup with recent tx hashes from CSV so a restart doesn't
        # cause a burst of re-fires from the first poll's 500-trade window.
        self._prime_seen_tx()
        # Rebuild market_exposure from live_orders.jsonl — survives restarts AND
        # day rollovers (the 2026-05-27 v1.36 dual-side bug came from losing
        # this state when a UTC midnight hit between two opposite-side fades).
        if self.live:
            self._rebuild_market_exposure()
        print(f"[fade-bot] mode={'LIVE' if live else 'PAPER'}")
        print(f"[fade-bot] tracking {len(self.target_wallets)} target wallets")
        print(f"[fade-bot] preloaded {len(self.market_cache)} markets from CLOB index")
        print(f"[fade-bot] primed {len(self.seen_tx_set)} tx hashes from history")

        # ── On-chain real-time signal source (v1.40) ────────────────────────
        # Background thread watches Polygon for target-wallet TransferSingle
        # events and pushes data-api-shaped trades into a thread-safe queue that
        # the main loop drains into process_trade (single-threaded — no races).
        # ── Elo model filter (v1.41) ────────────────────────────────────────
        self.cs2_model = None
        self.lol_model = None
        if MODEL_FILTER_ENABLED:
            try:
                from cs2_model import CS2Model
                self.cs2_model = CS2Model()
                print(f"[fade-bot] CS2 Elo model ON "
                      f"({len(self.cs2_model.elo_by_id)} teams, min_edge={MODEL_FILTER_MIN_EDGE})")
            except Exception as e:
                print(f"[fade-bot] CS2 Elo model load failed (filter disabled): {e}")
                self.cs2_model = None
            # LoL model: used for OBSERVE-ONLY paper pricing of LoL markets.
            try:
                from cs2_model import CS2Model
                self.lol_model = CS2Model(game="lol")
                if self.lol_model.elo_by_id:
                    print(f"[fade-bot] LoL Elo model ON "
                          f"({'OBSERVE-ONLY' if LOL_OBSERVE_ONLY else 'LIVE via gate'}) "
                          f"({len(self.lol_model.elo_by_id)} teams)")
                else:
                    print("[fade-bot] LoL Elo model empty (no lol_*.parquet yet) — LoL obs will log unmatched")
            except Exception as e:
                print(f"[fade-bot] LoL Elo model load failed: {e}")
                self.lol_model = None

        # ── SHADOW MODEL (Cowork esports_model Predictor) — A/B, never trades ──
        # Loads the gradient-boosted win-prob model and logs its decision alongside
        # the live Elo filter on every CS2 fade, WITHOUT changing what we trade.
        # Fully fail-safe: any import/load error leaves shadow off and trading
        # completely unaffected (e.g. if sklearn isn't installed).
        self.shadow = {}
        if SHADOW_MODEL_ENABLED:
            try:
                import sys as _sys
                _sp = str(ROOT / "esports_model" / "src")
                if _sp not in _sys.path:
                    _sys.path.insert(0, _sp)
                from predict import Predictor as _Pred
                for _g in ("cs2", "lol"):
                    try:
                        self.shadow[_g] = _Pred(_g)
                    except Exception as _e:
                        print(f"[fade-bot] shadow model {_g} load failed: {_e}")
                if self.shadow:
                    print(f"[fade-bot] v2 model ON (PRIMARY live gate since v1.54; "
                          f"Elo comparison logged): {list(self.shadow)}")
            except Exception as e:
                print(f"[fade-bot] shadow model disabled ({e}) — trading unaffected")
                self.shadow = {}

        import queue as _queue
        self.onchain_queue: "_queue.Queue" = _queue.Queue(maxsize=2000)
        self.onchain = None
        if ONCHAIN_ENABLED:
            try:
                from onchain_listener import OnChainListener
                import requests as _rq
                token_index = self._build_token_index()
                try:
                    self._token_index_mtime = (ES_DIR / "clob_esports_markets.parquet").stat().st_mtime
                except OSError:
                    self._token_index_mtime = 0.0
                self.onchain = OnChainListener(
                    wallets=self.target_wallets,
                    token_index=token_index,
                    on_signal=self._enqueue_onchain_signal,
                    clob_session=_rq.Session(),  # dedicated session (thread isolation)
                    log=print,
                    gate=(self._onchain_gate if ONCHAIN_GATE_ENABLED else None),
                )
                self.onchain.start()
                print(f"[fade-bot] on-chain listener started "
                      f"({len(token_index)} tokens indexed, {len(self.target_wallets)} wallets)")
            except Exception as e:
                print(f"[fade-bot] on-chain listener failed to start: {e}")
                self.onchain = None

    def _enqueue_onchain_signal(self, trade: dict):
        """Callback from the listener thread. Just enqueue — processing happens
        single-threaded in the main loop to avoid races on shared state."""
        try:
            self.onchain_queue.put_nowait(trade)
        except Exception:
            pass  # queue full — drop (main loop is behind; rare)

    def _rebuild_market_exposure(self):
        """Reconstruct self.market_exposure from live_orders.jsonl.

        Sums matched BUY cost per (cid, outcome) and subtracts matched SELL
        cost. Markets that have already resolved (we can detect via the eval'd
        live_results.csv) are excluded — their exposure is no longer relevant.

        Called once at bot startup so:
          - Restarts don't lose hedge-guard state
          - UTC day rollovers don't lose hedge-guard state
        """
        orders_path = OUT_DIR / "live_orders.jsonl"
        if not orders_path.exists():
            return
        # First pass: gather resolved cids from live_results.csv (status WIN/LOSS/TP_*)
        # so we don't keep ghost exposure on settled markets.
        resolved_cids: set[str] = set()
        results_path = OUT_DIR / "live_results.csv"
        if results_path.exists():
            try:
                import csv as _csv
                with results_path.open(encoding="utf-8") as fh:
                    for r in _csv.DictReader(fh):
                        if r.get("status") in ("WIN", "LOSS", "TP_SOLD", "TP_LOSS"):
                            cid = r.get("fade_condition", "")
                            if cid:
                                resolved_cids.add(cid)
            except Exception as e:
                print(f"[fade-bot] exposure rebuild: results.csv read failed: {e}")

        # Second pass: scan orders, sum BUY cost − SELL cost per (cid, outcome).
        exposure: dict[tuple[str, str], float] = {}
        try:
            with orders_path.open(encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        o = json.loads(line)
                    except Exception:
                        continue
                    if str(o.get("status", "")).lower() != "matched":
                        continue
                    cid = o.get("fade_condition", "")
                    if not cid or cid in resolved_cids:
                        continue
                    outcome = o.get("our_outcome", "")
                    cost = float(o.get("cost_usd") or 0)
                    side = str(o.get("side", "BUY")).upper()
                    key = (cid, outcome)
                    if side == "BUY":
                        exposure[key] = exposure.get(key, 0.0) + cost
                    elif side == "SELL":
                        exposure[key] = exposure.get(key, 0.0) - cost
        except Exception as e:
            print(f"[fade-bot] exposure rebuild: orders.jsonl read failed: {e}")
            return
        # Drop entries that net out to ~zero (fully closed positions)
        self.market_exposure = {k: v for k, v in exposure.items() if v > 0.5}
        n = len(self.market_exposure)
        if n:
            total = sum(self.market_exposure.values())
            # Count markets where we hold multiple outcomes (would be hedge-blocked now)
            cids_by_outcome: dict[str, set[str]] = {}
            for (cid, oc), _ in self.market_exposure.items():
                cids_by_outcome.setdefault(cid, set()).add(oc)
            multi = sum(1 for ocs in cids_by_outcome.values() if len(ocs) > 1)
            print(f"[fade-bot] exposure rebuilt: {n} (cid,outcome) positions, "
                  f"${total:.2f} total, {multi} markets with dual-side holdings")
        else:
            print(f"[fade-bot] exposure rebuilt: no open positions")

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

    def _build_token_index(self) -> dict:
        """token_id(str) -> (condition_id, outcome, slug) for the on-chain listener."""
        idx = {}
        try:
            import pandas as pd
            p = ES_DIR / "clob_esports_markets.parquet"
            if not p.exists():
                return idx
            df = pd.read_parquet(p, columns=["condition_id", "tokens", "slug"])
            for _, row in df.iterrows():
                cid = row["condition_id"]; slug = row.get("slug") or ""
                try:
                    for t in row["tokens"]:
                        tid = t.get("token_id"); o = t.get("outcome")
                        if tid and o:
                            idx[str(tid)] = (cid, o, slug)
                except TypeError:
                    continue
        except Exception as e:
            print(f"[fade-bot] token index build failed: {e}")
        return idx

    def _load_cs2_windows(self) -> list[tuple[float, float]]:
        """Build [(start_ts, end_ts), ...] match windows for OPEN CS2 *and LoL*
        markets, so the on-chain listener polls during both (LoL is observe-only).

        A real match market has a populated game_start (prop/futures markets like
        'will-cs2-market-cap-...' / 'will-...-win-worlds' do not), so requiring
        game_start excludes that noise. Valorant VCT is EXCLUDED (its slugs carry
        'league'). Window = [start - PRE, start + POST]."""
        import pandas as pd
        p = ES_DIR / "clob_esports_markets.parquet"
        if not p.exists():
            return []
        df = pd.read_parquet(p, columns=["slug", "game_start", "closed", "archived"])
        sl = df["slug"].fillna("").str.lower()
        is_cs2 = sl.str.contains("cs2-|-cs2|csgo-|-csgo")
        is_lol = (sl.str.startswith(("lol-", "arch-lol-", "league-"))
                  | sl.str.contains("league-of-legends"))
        is_val = sl.str.contains("vct|valorant")
        m = df[(is_cs2 | (is_lol & ~is_val)) & (~df["closed"].astype(bool)) & (~df["archived"].astype(bool))]
        gs = pd.to_datetime(m["game_start"], errors="coerce", utc=True).dropna()
        out = []
        for t in gs:
            start = t.timestamp()
            out.append((start - CS2_WINDOW_PRE_S, start + CS2_WINDOW_POST_S))
        return out

    def _onchain_gate(self) -> bool:
        """Gate for the on-chain listener: True iff a CS2 match window is open now.

        Called from the listener thread every poll. Caches the window list and
        rebuilds it from the parquet at most every CS2_WINDOW_REFRESH_S. Fails
        OPEN (returns True) on any error or before the first successful load, so a
        data glitch can never silently stop detection."""
        now = time.time()
        try:
            if now - getattr(self, "_cs2_windows_at", 0.0) > CS2_WINDOW_REFRESH_S:
                self._cs2_windows = self._load_cs2_windows()
                self._cs2_windows_at = now
        except Exception as e:
            self._cs2_windows_at = now              # don't hammer on repeated errors
            if not getattr(self, "_cs2_windows", None):
                return True                         # never loaded -> fail open
            print(f"[fade-bot] gate window reload failed (using stale): {e}")
        windows = getattr(self, "_cs2_windows", None)
        if windows is None:
            return True                             # not loaded yet -> fail open
        active = any(s <= now <= e for s, e in windows)
        if active != getattr(self, "_gate_active", None):
            self._gate_active = active
            open_n = sum(1 for s, e in windows if s <= now <= e)
            print(f"[fade-bot] on-chain gate -> "
                  f"{'ACTIVE (CS2 match window open, %d)' % open_n if active else 'IDLE (no live CS2 match)'} "
                  f"[{len(windows)} windows known]")
        return active

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
            # Wallet equity for Kelly sizing (refreshed every eval cycle, ~10 min).
            eq = d.get("wallet_total_equity_usd")
            if eq:
                self.wallet_equity = float(eq)
            self.daily_pnl_mtime = cur_mtime
        except Exception as e:
            print(f"[fade-bot] daily_pnl reload failed: {e}")

    def maybe_reload_token_index(self):
        """Hot-reload the esports market index so we pick up NEWLY-created markets
        (CS2 or LoL) WITHOUT a restart. CRITICAL: the on-chain listener drops any
        trade on a token it doesn't know, so a stale index = blind to new markets.
        We saw this directly — a 3-day-old process had missed ~1,400 new tokens —
        and it's the #1 way we'd miss LoL the moment GRID lists it. The refresh task
        rewrites the parquet ~hourly; this re-reads on mtime change."""
        if not getattr(self, "onchain", None):
            return
        try:
            m = (ES_DIR / "clob_esports_markets.parquet").stat().st_mtime
        except OSError:
            return
        if m <= getattr(self, "_token_index_mtime", 0.0):
            return
        try:
            idx = self._build_token_index()
            if idx:
                before = len(self.onchain.token_index or {})
                self.onchain.token_index = idx
                self._token_index_mtime = m
                self.write_event({"type": "token_index_reloaded",
                                  "tokens": len(idx), "added": len(idx) - before})
                print(f"[fade-bot] token index reloaded: {len(idx)} tokens "
                      f"({len(idx) - before:+d} vs prev)")
        except Exception as e:
            print(f"[fade-bot] token index reload failed: {e}")

    def _model_for_slug(self, slug: str):
        """Route a market to the right Elo model: CS2 -> cs2_model, LoL -> lol_model
        (Valorant excluded). Returns None if no model covers the slug. Keeps CS2
        behaviour identical; lets a LoL go-live be a clean LOL_OBSERVE_ONLY flip."""
        s = (slug or "").lower()
        if s.startswith(("cs2-", "csgo-")):
            return self.cs2_model
        if self._is_lol_slug(s):
            return self.lol_model
        return None

    def _shadow_compare(self, slug, our_outcome, other_outcome, our_entry, elo_p, elo_edge, tx):
        """A/B: log the Cowork esports_model Predictor's call next to the live Elo
        filter. PURELY OBSERVATIONAL — never affects the trade. Exception-safe so a
        shadow error can never touch the trading path."""
        try:
            s = (slug or "").lower()
            g = "cs2" if s.startswith(("cs2-", "csgo-")) else ("lol" if self._is_lol_slug(s) else None)
            pred = self.shadow.get(g) if g else None
            if pred is None:
                return
            elo_pass = int(elo_edge > MODEL_FILTER_MIN_EDGE)
            r = pred.predict(our_outcome, other_outcome)
            row = {"type": "shadow_compare", "tx": tx, "slug": slug, "game": g,
                   "our_outcome": our_outcome, "our_entry": our_entry,
                   "elo_p": round(elo_p, 4), "elo_edge": round(elo_edge, 4), "elo_pass": elo_pass}
            if r.get("ok"):
                sp = r["model_prob_a"]; se = sp - our_entry
                spass = int(se > MODEL_FILTER_MIN_EDGE)
                row.update({"shadow_ok": True, "shadow_p": round(sp, 4),
                            "shadow_edge": round(se, 4), "shadow_pass": spass,
                            "agree_pass": int(elo_pass == spass)})
            else:
                row.update({"shadow_ok": False, "shadow_reason": r.get("error", "")[:60]})
            self.write_event(row)
        except Exception:
            pass  # shadow must NEVER affect trading

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
                # Keep the on-chain listener's wallet filter in sync
                if getattr(self, "onchain", None):
                    self.onchain.update_wallets(wallets)
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

    def _is_lol_slug(self, slug: str) -> bool:
        """True for League of Legends markets. EXCLUDES Valorant VCT, whose slugs
        also contain 'league' (e.g. '...-emea-league-stage') — the contamination
        found in the LoL audit."""
        s = (slug or "").lower()
        if "vct" in s or "valorant" in s:
            return False
        return s.startswith(("lol-", "arch-lol-", "league-")) or "league-of-legends" in s

    def _tier_for(self, out_a: str, out_b: str, slug: str):
        """tier_ord (s=4,a=3,b=2,c=1,d=0) for a CS2 matchup, or None if unknown.
        Source: cowork_snapshot/gamedata/bo3/tier_index.parquet (built weekly from
        the bo3 dump by analysis/build_tier_index.py; includes UPCOMING matches).
        Match = normalized team pair + market-slug date within +/-2 days."""
        import re as _re
        p = ROOT / "cowork_snapshot" / "gamedata" / "bo3" / "tier_index.parquet"
        try:
            mt = p.stat().st_mtime
        except OSError:
            return None
        if mt > getattr(self, "_tieridx_mtime", 0.0):
            try:
                import pandas as _pd
                df = _pd.read_parquet(p)
                idx = {}
                for r in df.itertuples(index=False):
                    idx.setdefault((r.a, r.b), []).append((r.date, int(r.tier_ord)))
                self._tieridx = idx
                self._tieridx_mtime = mt
                print(f"[fade-bot] tier index loaded: {len(df):,} rows")
            except Exception as e:
                print(f"[fade-bot] tier index load failed: {e}")
                return None
        idx = getattr(self, "_tieridx", None)
        if not idx:
            return None
        def _tn(s):
            s = (s or "").lower()
            s = _re.sub(r"\b(esports|esport|e sports|gaming|team|clan|club|gg)\b", " ", s)
            return _re.sub(r"[^a-z0-9]", "", s)
        na, nb = _tn(out_a), _tn(out_b)
        ents = idx.get((min(na, nb), max(na, nb)))
        if not ents:
            return None
        md = _re.search(r"(\d{4}-\d{2}-\d{2})", slug or "")
        if not md:
            return ents[-1][1]
        from datetime import date as _date
        try:
            target = _date.fromisoformat(md.group(1))
            best = min(ents, key=lambda e: abs((_date.fromisoformat(e[0]) - target).days))
            if abs((_date.fromisoformat(best[0]) - target).days) <= 2:
                return best[1]
        except Exception:
            return ents[-1][1]
        return None

    def _clob_book(self, token_id: str):
        """Return (best_ask, depth_usd_within_2c) for a token, or (None, 0.0).
        depth = $ liquidity available at <= best_ask + 2c (can we actually fill?)."""
        try:
            r = self.session.get("https://clob.polymarket.com/book",
                                 params={"token_id": str(token_id)}, timeout=6)
            if r.status_code != 200:
                return None, 0.0
            asks = sorted(((float(a["price"]), float(a["size"]))
                           for a in (r.json().get("asks") or [])), key=lambda x: x[0])
            if not asks:
                return None, 0.0
            best = asks[0][0]
            depth = sum(p * s for p, s in asks if p <= best + 0.02)
            return best, round(depth, 2)
        except Exception:
            return None, 0.0

    def _observe_lol(self, *, slug, cid, wallet, their_side, their_outcome,
                     their_price, our_outcome, our_entry, our_token_id, other,
                     strategy, tx):
        """PAPER-ONLY observation of a LoL fade opportunity. Prices it with the
        LoL Elo model and logs LIVE order-book depth — the liquidity test that
        decides whether LoL is even tradeable. NEVER places an order."""
        # Debounce: one observation per (wallet, market) per window.
        dkey = ("lolobs", wallet, cid)
        nowt = time.time()
        if nowt - self.last_signal_ts.get(dkey, 0.0) < MIN_SECONDS_BETWEEN_SAME_TARGET_SAME_MARKET:
            return
        self.last_signal_ts[dkey] = nowt

        model_p = model_edge = None
        m_games_ours = m_games_other = None
        reason = "no_model"
        if self.lol_model is not None and self.lol_model.elo_by_id:
            pred = self.lol_model.predict(our_outcome, other)
            if pred and pred.get("ok"):
                model_p = pred["model_pA"]
                model_edge = round(model_p - our_entry, 4)
                m_games_ours, m_games_other = pred.get("gamesA"), pred.get("gamesB")
                reason = "ok"
            else:
                reason = (pred or {}).get("reason", "no_pred")

        best_ask, depth = self._clob_book(our_token_id) if our_token_id else (None, 0.0)
        fillable_bet = depth >= (LIVE_BET_USD if self.live else PAPER_BET_USD)
        would_fade = (model_edge is not None and model_edge > MODEL_FILTER_MIN_EDGE
                      and best_ask is not None and fillable_bet)

        row = {
            "ts": round(nowt, 2), "slug": slug, "condition_id": cid,
            "target_wallet": wallet, "strategy": strategy,
            "their_side": their_side, "their_outcome": their_outcome,
            "their_price": their_price, "our_outcome": our_outcome,
            "our_entry": our_entry,
            "model_p": round(model_p, 4) if model_p is not None else "",
            "model_edge": model_edge if model_edge is not None else "",
            "model_reason": reason,
            "games_ours": m_games_ours if m_games_ours is not None else "",
            "games_other": m_games_other if m_games_other is not None else "",
            "best_ask": round(best_ask, 4) if best_ask is not None else "",
            "book_depth_usd": depth,
            "fillable_bet": int(fillable_bet),
            "would_fade": int(bool(would_fade)),
        }
        # dedicated CSV for liquidity analysis + event log
        path = OUT_DIR / "lol_observations.csv"
        newfile = not path.exists()
        try:
            with path.open("a", encoding="utf-8", newline="") as fh:
                w = _csv.DictWriter(fh, fieldnames=list(row.keys()))
                if newfile:
                    w.writeheader()
                w.writerow(row)
        except Exception as e:
            print(f"[fade-bot] lol_obs write failed: {e}")
        self.write_event({"type": "lol_observation", **row})
        self.lol_obs_count = getattr(self, "lol_obs_count", 0) + 1

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
        if FOLLOW_ENABLED and wallet in self.follow_wallets:
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

        # SINGLE-MAP/GAME FILTER (v1.39). Skip Bo1 per-map markets — they're
        # coin flips (live ROI -8.1% vs -3.5% for series). LIVE only; PAPER
        # keeps collecting so we can keep validating the rule.
        if self.live and SKIP_SINGLE_MAP_MARKETS and is_single_map_market(slug):
            self.write_event({"type": "skip_single_map", "tx": tx, "slug": slug})
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

        # STALL DETECTION counter (v1.41): count every genuine target-wallet
        # signal that reaches the fade logic, BEFORE any filtering (model
        # filter, caps, single-map). The stall detector uses THIS — not the
        # count of placed fades — so it only alarms when target activity truly
        # stops (dead feed / no matches), not when the model filter is just
        # being selective and placing few orders.
        self.target_signals_seen = getattr(self, "target_signals_seen", 0) + 1

        # STRATEGY ROUTING
        # FADE:   we BUY the opposite outcome's token (target loses → we win)
        # FOLLOW: we BUY the same outcome's token at the same price (target wins → we win)
        if strategy == "fade":
            if their_side == "BUY":
                # target bullish their_outcome → fade = buy the OTHER side, whose
                # price is ~1 - their_price.
                our_outcome = other
                our_entry = round(1 - their_price, 4)
            else:
                # target SELL = exiting / shorting their_outcome → fade = buy the
                # SAME outcome they sold. We buy their_outcome, so our entry is
                # that outcome's OWN price (their_price), NOT 1 - their_price.
                # (Bug through v1.48: used 1 - their_price here, so we bid the
                # complement — e.g. 0.295 for a Vitality token trading at 0.705 —
                # which never filled AND produced a phantom model edge. v1.49.)
                our_outcome = their_outcome
                our_entry = round(their_price, 4)
        else:  # follow
            if their_side == "BUY":
                our_outcome = their_outcome
                our_entry = round(their_price, 4)
            else:
                # target SELL = exiting their_outcome → follow = buy the other side
                our_outcome = other
                our_entry = round(1 - their_price, 4)
        our_token_id = mkt["tokens"].get(our_outcome)

        # ── LoL: observe ALWAYS, trade only if live-enabled (v1.55) ─────────
        # Every LoL signal is logged with model edge + live book depth — this data
        # stream feeds backtest_lol.py and must keep flowing whether or not LoL
        # trades. If the kill switch (LOL_OBSERVE_ONLY=1) is set, stop here;
        # otherwise fall through to the SAME gate + caps + order path as CS2.
        # (Valorant excluded inside _is_lol_slug.)
        if self._is_lol_slug(slug):
            self._observe_lol(slug=slug, cid=condition_id, wallet=wallet,
                              their_side=their_side, their_outcome=their_outcome,
                              their_price=their_price, our_outcome=our_outcome,
                              our_entry=our_entry, our_token_id=our_token_id,
                              other=other, strategy=strategy, tx=tx)
            if LOL_OBSERVE_ONLY:
                return

        bet = LIVE_BET_USD if self.live else PAPER_BET_USD

        # UTC day rollover — reset DAILY counters only.
        # IMPORTANT: do NOT reset self.market_exposure here. Exposure tracks
        # *positions held* (cid, outcome) → $ committed, which persist across
        # days until the market resolves or we sell. Clearing it nightly caused
        # the opposite-side hedge guard to miss prior-day positions, leading
        # to bot buying both sides of the same market (v1.36 bug, discovered
        # on cs2-3dmax-mgc-2026-05-27 — locked guaranteed -$1.15).
        today = datetime.now(timezone.utc).date()
        if today != self.day_started:
            self.day_started = today
            self.daily_pnl = 0
            self.daily_risk_usd = 0.0
            self.fades_today = 0
            self.fades_by_wallet_today.clear()
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

        # Per-WALLET daily cap (v1.39) — stop one hyperactive target wallet from
        # dominating the book. LIVE only. Applied before order placement; the
        # counter is bumped only when we actually place (see fade-count bump).
        if self.live and strategy == "fade":
            wcount = self.fades_by_wallet_today.get(wallet, 0)
            if wcount >= MAX_FADES_PER_WALLET_PER_DAY:
                self.write_event({"type": "skip_wallet_daily_cap", "tx": tx,
                                  "wallet": wallet, "count": wcount,
                                  "cap": MAX_FADES_PER_WALLET_PER_DAY})
                return

        # Per-market exposure cap
        exp_key = (condition_id, our_outcome)
        prior = self.market_exposure.get(exp_key, 0.0)
        if prior + bet > MAX_PER_MARKET_USD:
            self.write_event({"type": "skip_market_cap", "cid": condition_id,
                              "our_outcome": our_outcome, "prior": prior, "tx": tx})
            return

        # OPPOSITE-SIDE HEDGE GUARD: if we already hold the other side of
        # this binary market, taking this trade locks in a guaranteed loss
        # (we'd pay >$1.00 total for a $1.00 payout). This happens when
        # two target wallets bet opposite sides on the same market and we
        # try to fade both. (2026-05-24 — discovered on cs2-fal2-lgc-2026-05-24
        # where we bought both Falcons and Legacy moneyline = guaranteed -$6.84.)
        for other_outcome in mkt["outcomes"]:
            if other_outcome == our_outcome:
                continue
            opp_exposure = self.market_exposure.get((condition_id, other_outcome), 0.0)
            if opp_exposure > 0:
                self.write_event({"type": "skip_opposite_side_held", "tx": tx,
                                  "cid": condition_id,
                                  "our_outcome": our_outcome,
                                  "opposite_outcome": other_outcome,
                                  "opposite_exposure_usd": opp_exposure,
                                  "slug": slug})
                return

        # Per-(target, market) debounce — drop rapid repeats from same target on same market
        debounce_key = (wallet, condition_id)
        now_ts = time.time()
        last = self.last_signal_ts.get(debounce_key, 0.0)
        if now_ts - last < MIN_SECONDS_BETWEEN_SAME_TARGET_SAME_MARKET:
            self.write_event({"type": "skip_debounce", "wallet": wallet, "cid": condition_id, "tx": tx})
            return
        self.last_signal_ts[debounce_key] = now_ts

        # ── Elo MODEL FILTER (v1.41) — LIVE only ────────────────────────────
        # Only place a real-money fade if the Elo model also likes our side.
        # our_entry ≈ market price of our fade side; model gives its probability.
        # edge = model_prob(our side) − market_price(our side). Require > min.
        gate_edge = None   # set by the gate below; drives maker-vs-taker execution
        if self.live and MODEL_FILTER_ENABLED and strategy == "fade":
            # MODEL-EDGE GATE (v1.54, Ship #1). Bet only when the win-prob model rates
            # OUR fade side underpriced by >= MODEL_FILTER_MIN_EDGE (now 0.10). PRIMARY
            # model = the v2 gradient-boosted Predictor (self.shadow), which the live
            # shadow A/B + a triple-confirmed OOS backtest showed beats Elo (+20.6% @3c
            # at edge>=0.10). Fall back to the Elo model only when v2 can't price the
            # matchup, or entirely if v2 failed to load (fail-safe = old Elo behaviour).
            other_outcome = [o for o in mkt["outcomes"] if o != our_outcome]
            other_outcome = other_outcome[0] if other_outcome else ""
            game = ("cs2" if slug.lower().startswith(("cs2-", "csgo-"))
                    else ("lol" if self._is_lol_slug(slug) else None))
            v2 = self.shadow.get(game) if game else None
            model_p_ours = None; used = None
            if v2 is not None:
                try:
                    r2 = v2.predict(our_outcome, other_outcome)
                    if r2.get("ok"):
                        model_p_ours = r2["model_prob_a"]; used = "v2"
                        # Keep the Elo-vs-v2 comparison stream alive (shadow_compare
                        # events) so we can continuously verify v2 stays ahead of Elo
                        # now that v2 is the PRIMARY. Roles are swapped vs v1.53 but
                        # the event schema is identical (elo_* vs shadow_* fields).
                        try:
                            em = self._model_for_slug(slug)
                            ep = em.predict(our_outcome, other_outcome) if em else None
                            if ep and ep.get("ok"):
                                self._shadow_compare(slug, our_outcome, other_outcome,
                                                     our_entry, ep["model_pA"],
                                                     ep["model_pA"] - our_entry, tx)
                        except Exception:
                            pass
                except Exception:
                    model_p_ours = None
            if model_p_ours is None:   # v2 unavailable/unmatched -> Elo fallback
                model = self._model_for_slug(slug)
                if model is None or not getattr(model, "elo_by_id", None):
                    self.write_event({"type": "skip_model_no_coverage", "tx": tx,
                                      "slug": slug, "reason": "no_model_for_game"})
                    return
                pred = model.predict(our_outcome, other_outcome)
                if not pred or not pred.get("ok"):
                    self.write_event({"type": "skip_model_unmatched", "tx": tx, "slug": slug,
                                      "our_outcome": our_outcome, "other": other_outcome,
                                      "reason": (pred or {}).get("reason", "no_pred")})
                    return
                model_p_ours = pred["model_pA"]; used = "elo_fallback"
            model_edge = model_p_ours - our_entry      # model prob(our side) - price
            gate_edge = round(model_edge, 4)           # -> trade dict (maker/taker)
            if model_edge <= MODEL_FILTER_MIN_EDGE:
                self.write_event({"type": "skip_model_filter", "tx": tx, "slug": slug,
                                  "our_outcome": our_outcome, "our_entry": our_entry,
                                  "model_p": round(model_p_ours, 4),
                                  "model_edge": round(model_edge, 4),
                                  "min_edge": MODEL_FILTER_MIN_EDGE, "model": used})
                return
            self.write_event({"type": "model_filter_pass", "tx": tx, "slug": slug,
                              "our_outcome": our_outcome, "our_entry": our_entry,
                              "model_p": round(model_p_ours, 4),
                              "model_edge": round(model_edge, 4), "model": used})

            # ── v2 DECISION LAYER (v1.57, REPORT_V2 §3) ────────────────────────
            # OOS-validated on 1,600 CS2 markets, filter fit pre-Feb / eval Feb-Jun:
            # turns the fillable 5-15c mid-range from -6.6% to +4-6% ROI.
            # Rule 1 (all games): entry must be > 0.20 — the <=20c bucket ran -64%
            #   at quoted prices (thin longshot books; the fat "tail" ROI there was
            #   never fillable). Supersedes the v1.54 floor of 0.10 for gated fades.
            # Rule 2 (CS2 only — bo3 tier feed): tier must be KNOWN (-16% on
            #   unjoined/obscure events) and NON-S (sharp markets; -5.7% measured).
            #   LoL gets rule 1 only: no LoL tier feed, filter validated on CS2.
            if our_entry <= 0.20:
                self.write_event({"type": "skip_bet_filter", "tx": tx, "slug": slug,
                                  "reason": "entry<=0.20 thin-longshot bucket",
                                  "our_entry": our_entry})
                return
            if game == "cs2":
                tier_ord = self._tier_for(our_outcome, other_outcome, slug)
                if tier_ord is None:
                    self.write_event({"type": "skip_bet_filter", "tx": tx, "slug": slug,
                                      "reason": "tier unknown", "our_entry": our_entry})
                    return
                if tier_ord >= 4:
                    self.write_event({"type": "skip_bet_filter", "tx": tx, "slug": slug,
                                      "reason": "tier-S sharp market", "tier_ord": tier_ord})
                    return
                self.write_event({"type": "bet_filter_pass", "tx": tx, "slug": slug,
                                  "tier_ord": tier_ord, "our_entry": our_entry})

            # ── BOOK-DEPTH GUARD (v1.55) ───────────────────────────────────────
            # With LoL live and entries allowed down to 0.10, never fire a gated
            # fade into a book that can't fill our bet within 2c of the ask.
            # (One /book call per gate PASS only — a few per day.)
            depth = 0.0
            if our_token_id:
                _ba, depth = self._clob_book(our_token_id)
                if depth < bet:
                    self.write_event({"type": "skip_thin_book", "tx": tx, "slug": slug,
                                      "ask_depth": round(depth, 2), "bet": bet})
                    return

            # ── Quarter-Kelly sizing (Ship #4, OFF until gate proves out) ──────
            if KELLY_ENABLED:
                try:
                    equity = float(getattr(self, "wallet_equity", 0) or 0)
                    q, p = model_p_ours, our_entry
                    if equity > 0 and 0 < p < 1 and q > p:
                        frac = min(KELLY_FRACTION * (q - p) / (1 - p), KELLY_CAP_PCT)
                        stake = equity * frac
                        # cap by per-market headroom and 25% of ask-side depth
                        stake = min(stake, MAX_PER_MARKET_USD - prior)
                        if depth:
                            stake = min(stake, 0.25 * depth)
                        if stake >= KELLY_MIN_USD:
                            bet = round(stake, 2)
                            self.write_event({"type": "kelly_sized", "tx": tx,
                                              "stake": bet, "equity": round(equity, 2),
                                              "q": round(q, 4), "p": p,
                                              "depth_cap": round(depth or 0, 2)})
                except Exception as e:
                    self.write_event({"type": "kelly_error", "error": str(e)[:80], "tx": tx})
                    # fall through with flat bet — sizing must never block a gated trade

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
            "model_edge":     gate_edge,
            "tx_hash":        tx,
            # LATENCY INSTRUMENTATION:
            "their_fill_ts":   float(t.get("timestamp") or 0),
            "signal_seen_at":  signal_seen_at,
            "signal_lag_s":    round(signal_seen_at - float(t.get("timestamp") or signal_seen_at), 3),
        }

        # Update exposure trackers.
        #  - PAPER: count every simulated fade (paper has no real fills).
        #  - LIVE: do NOT count here. market_exposure must reflect ACTUAL matched
        #    fills — otherwise a signal that is floored, errors, or never fills
        #    still inflates exposure, and that phantom $ then blocks the WHOLE
        #    market via the per-market cap + opposite-side guard. This is exactly
        #    what stranded furia-9z with $45 of exposure and ZERO real orders
        #    (2026-06-18). LIVE exposure is added in place_live_order on a fill.
        if not self.live:
            self.market_exposure[exp_key] = prior + bet
        self.fades_today += 1
        if strategy == "fade":
            self.fades_by_wallet_today[wallet] = self.fades_by_wallet_today.get(wallet, 0) + 1

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
        # ── MAKER-FIRST EXECUTION (Ship #3, 2026-07-02) ────────────────────────
        # Measured mean fill cost was ~1.7c (533 fills) — most of the raw edge.
        # Post GTC AT the signal price (maker) and wait longer; pay the +1c taker
        # slippage ONLY when the model edge is big enough to be worth chasing
        # (>= MAKER_TAKER_EDGE) or when we have no edge reading (Elo-era behaviour).
        # On maker timeout we CANCEL and let it go — chasing spread on a thin edge
        # is exactly how the pre-v1.54 config bled out.
        m_edge = trade.get("model_edge")
        maker = (MAKER_FIRST_ENABLED and m_edge is not None
                 and m_edge < MAKER_TAKER_EDGE)
        if maker:
            price = round(min(MAX_ENTRY_PRICE, trade["our_entry"]), 2)
            fill_timeout = MAKER_FILL_TIMEOUT
        else:
            price = round(min(MAX_ENTRY_PRICE, trade["our_entry"] + ENTRY_SLIPPAGE), 2)
            fill_timeout = LIVE_FILL_TIMEOUT
        exec_mode = "maker" if maker else "taker"
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
                              "exec_mode": exec_mode,
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
            while time.time() - t0 < fill_timeout:
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
                          "exec_mode": exec_mode,
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
                "exec_mode": exec_mode,
                **{k: trade.get(k) for k in ("fade_condition", "fade_slug", "our_outcome",
                                              "target_wallet", "strategy", "model_edge")},
            }) + "\n")

        # Reflect the ACTUAL matched fill in the per-market exposure tracker that
        # the cap + opposite-side guards read. Only real fills count (see the note
        # at the signal-time increment) so unfilled/failed attempts can't leave
        # phantom exposure that blocks the market. (2026-06-18, v1.48)
        if final_matched > 0:
            ek = (trade.get("fade_condition"), trade.get("our_outcome"))
            self.market_exposure[ek] = self.market_exposure.get(ek, 0.0) + cost

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
                # ── On-chain signals first (they're ~100x fresher than data-api).
                # Drain the queue and process each. process_trade dedups by tx
                # hash, so the later data-api copy of the same trade is a no-op.
                drained = 0
                while True:
                    try:
                        oc = self.onchain_queue.get_nowait()
                    except Exception:
                        break
                    n_trades_seen += 1
                    drained += 1
                    lag = oc.get("_detect_lag_s")
                    self.write_event({"type": "onchain_signal", "tx": oc.get("transactionHash"),
                                      "wallet": oc.get("proxyWallet"), "slug": oc.get("slug"),
                                      "side": oc.get("side"), "outcome": oc.get("outcome"),
                                      "price": oc.get("price"), "detect_lag_s": lag})
                    self.process_trade(oc)
                    if drained >= 200:
                        break  # safety valve

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
                # Stall is judged on TARGET SIGNALS SEEN (pre-filter), not placed
                # fades — the model filter (v1.41) makes placed fades rare, so the
                # old fades-based stall would cry wolf constantly.
                n_signals_now = getattr(self, "target_signals_seen", 0)
                if time.time() - last_summary > 60:
                    pnl_str = f" daily_pnl=${self.daily_pnl:+.2f}" if self.live else ""
                    oc_str = ""
                    if getattr(self, "onchain", None):
                        o = self.onchain
                        lag = f"{o.last_detect_lag:.0f}s" if o.last_detect_lag is not None else "n/a"
                        gstr = "IDLE(no-cs2)" if getattr(o, "gated", False) else "active"
                        oc_str = (f" | onchain[conn={o.connected} gate={gstr} detected={o.n_detected} "
                                  f"emitted={o.n_emitted} dropped={o.n_dropped} last_lag={lag}]")
                    lol_str = f" lol_obs={getattr(self,'lol_obs_count',0)}" if getattr(self,'lol_obs_count',0) else ""
                    print(f"[fade-bot] heartbeat: trades_scanned={n_trades_seen} "
                          f"signals={n_signals_now} fades={n_fades_now} "
                          f"unique_tx={len(self.seen_tx_set)} targets={len(self.target_wallets)}{pnl_str}{lol_str}{oc_str}")

                    # ── Signal-stall detection ─────────────────────────────
                    now = time.time()
                    if n_signals_now > last_fades_value:
                        # Target-signal counter advanced — clear any active stall
                        if stall_active:
                            stall_duration = round(now - last_fades_change_at, 0)
                            print(f"[fade-bot] STALL RECOVERED after {stall_duration:.0f}s "
                                  f"({stall_duration/3600:.1f}h) — target signals resumed")
                            self.write_event({
                                "type": "signal_stall_recovered",
                                "ts": now,
                                "stall_seconds": stall_duration,
                                "signals_now": n_signals_now,
                                "trades_scanned": n_trades_seen,
                            })
                            notify(
                                f"✅ <b>Signals resumed</b>\n"
                                f"Stall ended after {stall_duration/3600:.1f}h. "
                                f"Target wallets are trading again.",
                                kind="signal_stall_recovered", cooldown=0,
                            )
                            try: stall_flag_path.unlink()
                            except FileNotFoundError: pass
                            stall_active = False
                        last_fades_value = n_signals_now
                        last_fades_change_at = now
                        last_scans_at_change = n_trades_seen
                    else:
                        # Target signals flat. Stall only if NO target wallet has
                        # traded for the threshold while we're still polling — i.e.
                        # genuine drought / dead feed, NOT the model filter being
                        # selective (placed fades can be 0 without a stall).
                        flat_seconds = now - last_fades_change_at
                        scans_since_change = n_trades_seen - last_scans_at_change
                        if (not stall_active
                                and flat_seconds > SIGNAL_STALL_SECONDS
                                and scans_since_change > 0):
                            print(f"[fade-bot] !!! SIGNAL STALL DETECTED !!! "
                                  f"target signals stuck at {n_signals_now} for {flat_seconds/3600:.1f}h "
                                  f"while {scans_since_change:,} trades scanned. "
                                  f"Bot healthy but no target-wallet activity.")
                            self.write_event({
                                "type": "signal_stall_detected",
                                "ts": now,
                                "stall_seconds": round(flat_seconds, 0),
                                "signals": n_signals_now,
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
                                f"No target-wallet trades for {flat_seconds/3600:.1f}h.\n"
                                f"Bot is polling fine ({scans_since_change:,} trades scanned), "
                                f"but no target wallets traded.\n\n"
                                f"<b>Likely cause:</b> {cause}.\n"
                                f"Run /diagnose for details.",
                                kind="signal_stall", cooldown=14400,  # 4h — don't re-alert until recovery
                            )
                            try:
                                stall_flag_path.write_text(json.dumps({
                                    "stall_started_at":  last_fades_change_at,
                                    "signals_at_stall":  n_signals_now,
                                    "detected_at":       now,
                                    "stall_seconds":     round(flat_seconds, 0),
                                }), encoding="utf-8")
                            except Exception:
                                pass
                            stall_active = True
                    # ───────────────────────────────────────────────────────

                    last_summary = now
                    self.maybe_reload_targets()
                    self.maybe_reload_token_index()   # pick up new markets w/o restart
                    if self.cs2_model is not None:
                        self.cs2_model.maybe_reload()
                    if self.lol_model is not None:
                        self.lol_model.maybe_reload()
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
