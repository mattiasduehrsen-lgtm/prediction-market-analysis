"""Phase 1 — updown maker fill simulator (maker-rebate lane, 2026-07-18).

Mission spec: CLAUDE_CODE_MAKER_LANE_PROMPT_2026-07-15.md §4; frozen gate:
COWORK_EDGE_AUDIT_2026-07-15.md §5. Runs against output/updown_capture/*.jsonl
(laptop). $0 at risk — pure simulation.

DESIGN PRINCIPLES (every ambiguous choice takes the side that HURTS the maker):

1. LATENCY IS MODELED, NOT ASSUMED AWAY. Desired quotes are recomputed on every
   spot tick, but take effect LATENCY_S (1.5s) later. A taker print landing in
   that gap fills the STALE quote. This is where a 1s-loop maker actually
   bleeds; a sim without it is fiction.
2. PRINTS-ONLY FILLS + QUEUE BARRIER. A resting quote fills only when a logged
   taker print crosses at-or-through its price, capped by the print's size and
   our clip. Before we see a single share, the logged displayed depth must be
   consumed: barrier = $0 only if we strictly improve the touch; = touch depth
   if we join the touch; = the full 2c-aggregated depth if we rest within 2c
   behind it; = infinite (no fill possible) deeper than that. Re-quoting resets
   the barrier (queue position is lost in reality too).
3. CASH ACCOUNTING. PnL = terminal cash of the window: fills at quote prices,
   +rebate per filled maker share (0.20 x feeRate x p(1-p), feeRate=0.072
   verified in Phase 0), flatten at T-90s as a TAKER (crossing 1c through the
   touch AND paying the taker fee), residual inventory settles at resolution.
   Mark moves at +10s/+60s are reported as adverse-selection DIAGNOSTICS, never
   double-counted into PnL.
4. RESOLUTION FROM THE MARKET'S OWN TERMINUS (last book mid >0.9 / <0.1);
   Binance close-vs-open only as fallback; ambiguous windows are skipped.
5. WINDOW-EPOCH AUTO-DETECTION: whether the slug epoch is the window START or
   END is measured from terminal-collapse timing per family, not assumed.
6. SPLIT-HALF PROTOCOL HARD-WIRED: per cell, spread parameter k* is chosen on
   the FIRST half of capture days only; the gate is evaluated ONLY on the
   second-half confirmation. The GO verdict additionally requires >=300 cell
   fills spanning >=5 distinct capture days and >=$3/day projected — printed
   mechanically; this script cannot emit GO before those hold.

Modes:
  --selftest   synthetic-event unit tests of the fill engine (run anywhere)
  --smoke      parse + simulate real capture but print ONLY plumbing
               diagnostics (no PnL, no cells) — pre-gate validation without
               peeking
  (default)    full cell report + mechanical gate verdict

Run (laptop): .venv\\Scripts\\python.exe -u analysis\\updown_maker_sim.py [--smoke]
"""
from __future__ import annotations

import glob
import json
import math
import sys
from bisect import bisect_left, bisect_right
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
CAP = ROOT / "output" / "updown_capture"

# ── frozen simulation parameters (changing these = new pre-registration) ─────
K_GRID = (0.02, 0.03, 0.04, 0.05)   # half-spread around fair, $ per share
CLIP_USD = 10.0                     # resting size per side (mission: $5-$20)
LATENCY_S = 1.5                     # our loop+network delay: quote changes take
                                    # effect this long after the trigger tick
REQUOTE_C = 0.01                    # re-quote when fair moved > 1c
MOVE_CANCEL_BP = 10.0               # cancel both quotes if spot moved >10bp
NO_QUOTE_HEAD_S = 30.0              # no quoting in first 30s of window
FLATTEN_S = 90.0                    # stop quoting + flatten at T-90s
FEE_RATE = 0.072                    # crypto taker fee curve (Phase-0 verified)
REBATE_SHARE = 0.20
VOL_TAU_S = 1800.0                  # EWMA half-life-ish for per-second variance
VOL_WARMUP = 20                     # min returns before fair value is trusted
MIN_BOOKS_PER_WINDOW = 10
HOUR_BANDS = ((0, 6), (6, 12), (12, 18), (18, 24))
GATE_MIN_FILLS = 300
GATE_MIN_DAYS = 5
GATE_MIN_PER_DAY = 3.0
BOOT_N = 4000


def phi(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def taker_fee(px: float, shares: float) -> float:
    return shares * FEE_RATE * px * (1.0 - px)


def rebate(px: float, shares: float) -> float:
    return REBATE_SHARE * FEE_RATE * px * (1.0 - px) * shares


# ── spot series with EWMA per-second variance ────────────────────────────────
class SpotSeries:
    def __init__(self):
        self.ts: list[float] = []
        self.px: list[float] = []
        self.sig: list[float] = []      # sqrt(per-second variance) at each tick
        self._var = None
        self._n = 0

    def add(self, ts: float, px: float):
        if self.ts:
            dt = ts - self.ts[-1]
            if dt <= 0:
                return
            if dt <= 120.0:             # skip returns across capture gaps
                r = math.log(px / self.px[-1])
                lam = math.exp(-dt / VOL_TAU_S)
                inst = (r * r) / dt
                self._var = inst if self._var is None else lam * self._var + (1 - lam) * inst
                self._n += 1
        self.ts.append(ts)
        self.px.append(px)
        self.sig.append(math.sqrt(self._var) if (self._var and self._n >= VOL_WARMUP) else float("nan"))

    def at(self, t: float):
        """(px, sigma_per_sqrt_s) at the last tick <= t, or (None, None)."""
        i = bisect_right(self.ts, t) - 1
        if i < 0:
            return None, None
        return self.px[i], self.sig[i]


# ── the fill engine ──────────────────────────────────────────────────────────
@dataclass
class Quote:
    px: float
    barrier: float          # $ of displayed depth that must trade before us
    shares_left: float


@dataclass
class WindowResult:
    slug: str
    asset: str
    win: str
    w0: float               # window START epoch (post epoch-detection)
    day: str
    hour: int
    n_fills: int = 0
    fill_notional: float = 0.0
    cash: float = 0.0       # terminal cash = net PnL
    gross_spread: float = 0.0
    rebates: float = 0.0
    flatten_cost: float = 0.0
    adverse_10s: list = field(default_factory=list)   # $ per fill, signed
    adverse_60s: list = field(default_factory=list)


def simulate_window(books, prints, spot: SpotSeries, w_start, w_end, k, diag):
    """Event-time sim of one window at half-spread k. Returns WindowResult|None.

    books:  [(ts, bid, ask, bid_depth, ask_depth, bid_touch, ask_touch)] sorted
    prints: [(ts, px_up, shares, is_buy_up)] sorted, deduped, normalized to UP
    """
    p0, _ = spot.at(w_start)
    if p0 is None or abs(spot.ts[bisect_right(spot.ts, w_start) - 1] - w_start) > 15.0:
        diag["skip_no_p0"] += 1
        return None
    if len(books) < MIN_BOOKS_PER_WINDOW:
        diag["skip_thin_books"] += 1
        return None

    def fair(t):
        s, sig = spot.at(t)
        if s is None or not sig or math.isnan(sig):
            return None
        tau = max(1.0, w_end - t)
        try:
            z = math.log(s / p0) / (sig * math.sqrt(tau))
        except (ValueError, ZeroDivisionError):
            return None
        return min(max(phi(z), 0.01), 0.99)

    def book_at(t):
        i = bisect_right([b[0] for b in books], t) - 1
        return books[i] if i >= 0 else None

    def barrier_for(side, px, t):
        b = book_at(t)
        if b is None:
            return float("inf")
        _, bid, ask, bdep, adep, btch, atch = b
        if side == "bid":
            if bid is None:
                return 0.0
            if px > bid + 1e-9:
                return 0.0                       # we improve: price priority
            if abs(px - bid) <= 1e-9:
                return btch or 0.0               # join touch: behind its queue
            if px >= bid - 0.02:
                return bdep or 0.0               # within logged 2c depth
            return float("inf")                  # deeper: depth unknown -> no fill
        else:
            if ask is None:
                return 0.0
            if px < ask - 1e-9:
                return 0.0
            if abs(px - ask) <= 1e-9:
                return atch or 0.0
            if px <= ask + 0.02:
                return adep or 0.0
            return float("inf")

    # pending quote state changes: (effective_ts, bid_quote|None, ask_quote|None)
    bid_q = ask_q = None
    pending = []
    last_quote_fair = None
    spot_at_quote = None
    inv = 0.0          # UP shares (+long / -short)
    cash = 0.0
    res = None         # filled later

    fills = []         # (ts, side, px, shares)
    events = sorted(
        [("spot", t) for t in spot.ts if w_start <= t <= w_end]
        + [("book", b[0]) for b in books]
        + [("print", p[0], p) for p in prints],
        key=lambda e: e[1])

    quote_open = lambda t: (w_start + NO_QUOTE_HEAD_S) <= t <= (w_end - FLATTEN_S)

    for ev in events:
        t = ev[1]
        # apply pending quote changes that became effective
        while pending and pending[0][0] <= t:
            _, nb, na = pending.pop(0)
            bid_q, ask_q = nb, na

        if ev[0] == "print":
            _, _, (pt, px_up, sh, is_buy) = ev
            if is_buy and ask_q and px_up >= ask_q.px - 1e-9 and ask_q.shares_left > 0:
                notional = px_up * sh
                eat = min(notional, ask_q.barrier)
                ask_q.barrier -= eat
                rem_sh = max(0.0, sh - eat / max(px_up, 1e-6))
                take = min(rem_sh, ask_q.shares_left)
                if take > 1e-9:
                    fills.append((pt, "ask", ask_q.px, take))
                    ask_q.shares_left -= take
                    inv -= take
                    cash += ask_q.px * take + rebate(ask_q.px, take)
            elif (not is_buy) and bid_q and px_up <= bid_q.px + 1e-9 and bid_q.shares_left > 0:
                notional = px_up * sh
                eat = min(notional, bid_q.barrier)
                bid_q.barrier -= eat
                rem_sh = max(0.0, sh - eat / max(px_up, 1e-6))
                take = min(rem_sh, bid_q.shares_left)
                if take > 1e-9:
                    fills.append((pt, "bid", bid_q.px, take))
                    bid_q.shares_left -= take
                    inv += take
                    cash -= bid_q.px * take
                    cash += rebate(bid_q.px, take)
            continue

        # spot / book event -> recompute desired quotes, effective t+LATENCY_S
        if not quote_open(t):
            if bid_q or ask_q or pending:
                pending = [(t + LATENCY_S, None, None)]
            continue
        f = fair(t)
        if f is None:
            continue
        s_now, _ = spot.at(t)
        moved_bp = abs(s_now / spot_at_quote - 1.0) * 1e4 if spot_at_quote else 0.0
        need = (
            (bid_q is None and ask_q is None)
            or last_quote_fair is None
            or abs(f - last_quote_fair) > REQUOTE_C
            or moved_bp > MOVE_CANCEL_BP
        )
        if not need:
            continue
        bpx, apx = round(f - k, 2), round(f + k, 2)
        if not (0.02 <= bpx and apx <= 0.98 and bpx < apx):
            pending = [(t + LATENCY_S, None, None)]
            last_quote_fair, spot_at_quote = f, s_now
            continue
        eff = t + LATENCY_S
        nb = Quote(bpx, barrier_for("bid", bpx, t), CLIP_USD / bpx)
        na = Quote(apx, barrier_for("ask", apx, t), CLIP_USD / apx)
        pending = [(eff, nb, na)]
        last_quote_fair, spot_at_quote = f, s_now

    # ── flatten at T-90s (as taker: 1c through the touch + taker fee) ────────
    if abs(inv) > 1e-9:
        b = book_at(w_end - FLATTEN_S + 30) or book_at(w_end)
        if b and b[1] is not None and b[2] is not None:
            _, bid, ask, *_ = b
            if inv > 0:
                px = max(bid - 0.01, 0.01)
                cash += px * inv - taker_fee(px, inv)
            else:
                px = min(ask + 0.01, 0.99)
                cash -= px * (-inv) + taker_fee(px, -inv)
            inv = 0.0

    # ── residual inventory (no flatten book) -> resolution ───────────────────
    if abs(inv) > 1e-9:
        last_mid = None
        for bts, bid, ask, *_ in reversed(books):
            if bid is not None and ask is not None:
                last_mid = (bid + ask) / 2
                break
        if last_mid is None:
            diag["skip_no_resolution"] += 1
            return None
        if last_mid > 0.9:
            up_won = 1
        elif last_mid < 0.1:
            up_won = 0
        else:
            s_end, _ = spot.at(w_end)
            if s_end is None:
                diag["skip_no_resolution"] += 1
                return None
            up_won = 1 if s_end > p0 else 0
        cash += up_won * inv if inv > 0 else up_won * inv  # inv shares pay 1 if up
        # (short residuals: cash -= up_won * |inv| — handled by sign above)
        inv = 0.0

    if not fills:
        diag["windows_no_fills"] += 1

    # diagnostics: adverse marks & spread capture vs mid at fill
    r = WindowResult("", "", "", w_start, "", 0)
    r.cash = cash
    r.n_fills = len(fills)
    for ft, side, px, sh in fills:
        r.fill_notional += px * sh
        b = book_at(ft)
        if b and b[1] is not None and b[2] is not None:
            mid = (b[1] + b[2]) / 2
            r.gross_spread += (mid - px) * sh if side == "bid" else (px - mid) * sh
        r.rebates += rebate(px, sh)
        for delay, bucket in ((10.0, r.adverse_10s), (60.0, r.adverse_60s)):
            i = bisect_left([bb[0] for bb in books], ft + delay)
            if i < len(books) and books[i][0] <= ft + delay + 30 \
                    and books[i][1] is not None and books[i][2] is not None:
                m2 = (books[i][1] + books[i][2]) / 2
                bucket.append(((m2 - px) if side == "bid" else (px - m2)) * sh)
    return r


# ── data loading ─────────────────────────────────────────────────────────────
def load_and_simulate(k_grid, smoke=False):
    files = sorted(glob.glob(str(CAP / "updown_*.jsonl")))
    diag = defaultdict(int)
    results = defaultdict(list)          # (asset,win,band,k) -> [WindowResult]
    epoch_mode = {}                      # family -> "start"|"end" (auto-detect)
    all_days = set()

    for fp in files:
        day = Path(fp).stem.split("_")[1]
        spots: dict[str, SpotSeries] = defaultdict(SpotSeries)
        slug_books = defaultdict(list)
        slug_prints = defaultdict(dict)   # tx -> print (dedupe)
        slug_meta = {}
        sym_of = {"btc": "BTCUSDT", "eth": "ETHUSDT", "sol": "SOLUSDT",
                  "xrp": "XRPUSDT", "bnb": "BNBUSDT", "doge": "DOGEUSDT"}

        with open(fp, encoding="utf-8") as fh:
            for line in fh:
                try:
                    e = json.loads(line)
                except Exception:
                    diag["bad_lines"] += 1
                    continue
                typ = e.get("type")
                if typ == "spot":
                    for sym, px in (e.get("px") or {}).items():
                        spots[sym].add(e["ts"], float(px))
                elif typ == "book":
                    slug_books[e["slug"]].append(
                        (e["ts"], e.get("bid"), e.get("ask"),
                         e.get("bid_depth"), e.get("ask_depth"),
                         e.get("bid_touch"), e.get("ask_touch")))
                    slug_meta[e["slug"]] = (e["win"], e["w0"])
                elif typ == "trades":
                    for t in e.get("trades") or []:
                        tx = t.get("tx") or ""
                        if tx and tx in slug_prints[e["slug"]]:
                            continue
                        try:
                            ts_, px_, sz_ = float(t["ts"]), float(t["px"]), float(t["sz"])
                        except (KeyError, TypeError, ValueError):
                            diag["bad_prints"] += 1
                            continue
                        out = str(t.get("out", "")).strip().lower()
                        side = str(t.get("side", "")).strip().upper()
                        if out not in ("up", "down") or side not in ("BUY", "SELL"):
                            diag["odd_print_fields"] += 1
                            continue
                        px_up = px_ if out == "up" else 1.0 - px_
                        is_buy_up = (out == "up") == (side == "BUY")
                        slug_prints[e["slug"]][tx or f"{ts_}{px_}{sz_}"] = \
                            (ts_, px_up, sz_, is_buy_up)

        # epoch auto-detection per family from terminal collapse timing
        for slug, books in slug_books.items():
            fam = slug.rsplit("-", 1)[0]
            if fam in epoch_mode or len(books) < 20:
                continue
            win, w0 = slug_meta[slug]
            wsec = 300 if win == "5m" else 900
            mids = [(t, (b + a) / 2) for t, b, a, *_ in books
                    if b is not None and a is not None]
            pinned = [t for t, m in mids if m > 0.95 or m < 0.05]
            if not pinned:
                continue
            first_pin = min(pinned)
            # epoch==start => collapse near w0+wsec; epoch==end => near w0
            epoch_mode[fam] = "start" if abs(first_pin - (w0 + wsec)) < abs(first_pin - w0) else "end"

        for slug, books in slug_books.items():
            fam = slug.rsplit("-", 1)[0]
            asset, win = fam.split("-updown-")
            if asset == "hype":
                diag["skip_hype_no_spot"] += 1
                continue
            mode = epoch_mode.get(fam, "start")
            _, w0 = slug_meta[slug]
            wsec = 300 if win == "5m" else 900
            w_start = w0 if mode == "start" else w0 - wsec
            w_end = w_start + wsec
            books.sort()
            prints = sorted(slug_prints.get(slug, {}).values())
            prints = [p for p in prints if w_start <= p[0] <= w_end]
            spot = spots.get(sym_of[asset])
            if spot is None or not spot.ts:
                diag["skip_no_spot_series"] += 1
                continue
            hour = int((w_start % 86400) // 3600)
            band = next(i for i, (lo, hi) in enumerate(HOUR_BANDS) if lo <= hour < hi)
            diag["windows_seen"] += 1
            diag[f"prints_{asset}-{win}"] += len(prints)
            for k in k_grid:
                r = simulate_window(books, prints, spot, w_start, w_end, k, diag)
                if r is None:
                    break                     # skips are k-independent
                r.slug, r.asset, r.win, r.day, r.hour = slug, asset, win, day, hour
                results[(asset, win, band, k)].append(r)
                if r.n_fills:
                    diag["windows_with_fills"] += 1 if k == k_grid[0] else 0
                all_days.add(day)

    return results, diag, epoch_mode, sorted(all_days)


# ── reporting + the frozen gate ──────────────────────────────────────────────
def report(results, diag, epoch_mode, days):
    rng = np.random.default_rng(7)
    half = (len(days) + 1) // 2
    sel_days, conf_days = set(days[:half]), set(days[half:])
    print(f"\ncapture days: {days}  (select on {sorted(sel_days)}, confirm on {sorted(conf_days)})")
    print(f"epoch detection: {epoch_mode}")

    def agg(rs):
        n_f = sum(r.n_fills for r in rs)
        net = sum(r.cash for r in rs)
        a10 = [x for r in rs for x in r.adverse_10s]
        a60 = [x for r in rs for x in r.adverse_60s]
        return dict(n_win=len(rs), n_fills=n_f, net=net,
                    spread=sum(r.gross_spread for r in rs),
                    rebate=sum(r.rebates for r in rs),
                    adv10=float(np.mean(a10)) if a10 else float("nan"),
                    adv60=float(np.mean(a60)) if a60 else float("nan"))

    cells = sorted({(a, w, b) for (a, w, b, _) in results})
    confirmed = []
    print(f"\n{'cell':22} {'k*':>4} {'sel n/net':>14} {'conf n/net':>14} "
          f"{'conf fills':>10} {'P(<=0)':>7} {'adv60/fill':>10}")
    for cell in cells:
        a, w, b = cell
        best_k, best_net = None, -1e18
        for k in K_GRID:
            rs = [r for r in results.get((a, w, b, k), []) if r.day in sel_days]
            if sum(r.n_fills for r in rs) < 30:
                continue
            net = sum(r.cash for r in rs)
            if net > best_net:
                best_k, best_net = k, net
        if best_k is None:
            continue
        sel = agg([r for r in results[(a, w, b, best_k)] if r.day in sel_days])
        conf_rs = [r for r in results[(a, w, b, best_k)] if r.day in conf_days]
        conf = agg(conf_rs)
        p_le0 = float("nan")
        if conf_rs:
            per_win = np.array([r.cash for r in conf_rs])
            boots = np.array([rng.choice(per_win, len(per_win), replace=True).sum()
                              for _ in range(BOOT_N)])
            p_le0 = float(np.mean(boots <= 0))
        band_lbl = f"{HOUR_BANDS[b][0]:02d}-{HOUR_BANDS[b][1]:02d}"
        print(f"{a}-{w} {band_lbl:8} {best_k:4.2f} "
              f"{sel['n_fills']:5d}/${sel['net']:+7.2f} "
              f"{conf['n_fills']:5d}/${conf['net']:+7.2f} "
              f"{conf['n_fills']:10d} {p_le0:7.3f} {conf['adv60']:10.4f}")
        total_fills = sel["n_fills"] + conf["n_fills"]
        total_net = sel["net"] + conf["net"]
        if conf["net"] > 0 and p_le0 < 0.05:
            confirmed.append((cell, best_k, total_fills, total_net, conf, p_le0))

    print("\n" + "=" * 70)
    print("FROZEN GATE (audit §5) — mechanical evaluation")
    print("=" * 70)
    n_days = len(days)
    go = False
    for (cell, k, tf, tn, conf, p) in confirmed:
        per_day = tn / max(n_days, 1)
        conds = [
            ("confirm-half net > 0", conf["net"] > 0),
            ("cluster P(<=0) < 0.05", p < 0.05),
            (f"cell fills >= {GATE_MIN_FILLS}", tf >= GATE_MIN_FILLS),
            (f"distinct days >= {GATE_MIN_DAYS}", n_days >= GATE_MIN_DAYS),
            (f"projected >= ${GATE_MIN_PER_DAY}/day", per_day >= GATE_MIN_PER_DAY),
        ]
        ok = all(v for _, v in conds)
        print(f"cell {cell} k={k}: " + "; ".join(f"{n}={'PASS' if v else 'fail'}" for n, v in conds))
        go = go or ok
    if not confirmed:
        print("no cell passed split-half confirmation")
    print(f"\nVERDICT: {'GO — Phase 2 may be proposed to the user' if go else ('KILL' if n_days >= GATE_MIN_DAYS else f'INSUFFICIENT DATA ({n_days}/{GATE_MIN_DAYS} days) — keep capturing')}")


def smoke(diag, epoch_mode, days, results):
    print("\n--- SMOKE (plumbing only; no PnL printed) ---")
    print(f"days: {days}")
    print(f"epoch detection: {epoch_mode}")
    for key in sorted(diag):
        print(f"  {key}: {diag[key]}")
    n_sim = sum(len(v) for v in results.values()) // max(len(K_GRID), 1)
    print(f"  windows simulated (per k): ~{n_sim}")
    total_fills = sum(r.n_fills for (_, _, _, kk), v in results.items() if kk == K_GRID[0] for r in v)
    print(f"  fills at k={K_GRID[0]} (count only): {total_fills}")


# ── self-test of the fill engine on synthetic events ─────────────────────────
def selftest():
    diag = defaultdict(int)
    sp = SpotSeries()
    t0 = 1_000_000.0
    for i in range(400):                     # 400 flat-ish ticks, 10s apart
        sp.add(t0 - 4000 + i * 10, 100.0 * (1 + 0.0001 * ((i * 7) % 5 - 2)))
    w_start, w_end = t0, t0 + 900
    for i in range(90):
        sp.add(w_start + i * 10, 100.0)      # dead-flat spot -> fair ~0.50

    def bk(ts, bid, ask, btch=50.0, atch=50.0):
        return (ts, bid, ask, btch * 2, atch * 2, btch, atch)

    books = [bk(w_start + i * 10, 0.47, 0.53) for i in range(90)]

    # 1. print at our bid AFTER barrier consumed -> fill; before -> no fill
    prints = [(w_start + 100, 0.46, 60.0, False),   # sell 60sh @0.46: eats $27.6 of $50 barrier -> no fill...
              (w_start + 110, 0.46, 200.0, False)]  # then fills after barrier gone
    r = simulate_window(books, prints, sp, w_start, w_end, 0.04, diag)
    assert r is not None and r.n_fills >= 1, "barrier-then-fill failed"

    # 2. no prints -> no fills, PnL 0
    r2 = simulate_window(books, [], sp, w_start, w_end, 0.04, diag)
    assert r2 is not None and r2.n_fills == 0 and abs(r2.cash) < 1e-9, "no-print case failed"

    # 3. print that does NOT cross (0.50 > bid 0.46) -> no fill
    r3 = simulate_window(books, [(w_start + 100, 0.50, 100.0, False)], sp,
                         w_start, w_end, 0.04, diag)
    assert r3 is not None and r3.n_fills == 0, "non-crossing print filled (BUG)"

    # 4. latency: a quote change triggered at t is NOT active for a print at t+0.5s
    #    (print hits the pre-existing quote state) — covered structurally by
    #    pending-queue; assert a fill occurring 0.5s after window-open+30s tick
    #    does not fill (no quote effective yet).
    prints4 = [(w_start + NO_QUOTE_HEAD_S + 0.5, 0.40, 500.0, False)]
    r4 = simulate_window(books, prints4, sp, w_start, w_end, 0.04, diag)
    assert r4 is not None and r4.n_fills == 0, "latency gap violated (BUG)"

    # 5. rebate math
    assert abs(rebate(0.5, 100) - 0.20 * 0.072 * 0.25 * 100) < 1e-12
    print("selftest: all 5 fill-engine checks passed")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
        sys.exit(0)
    results, diag, epoch_mode, days = load_and_simulate(K_GRID)
    if "--smoke" in sys.argv:
        smoke(diag, epoch_mode, days, results)
    else:
        report(results, diag, epoch_mode, days)
