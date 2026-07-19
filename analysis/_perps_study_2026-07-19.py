"""Perps funding-carry study — Cowork, 2026-07-19.

Runs on cowork_snapshot/perps/ ALONE (no network). Reproduces every number in
COWORK_PERPS_RESULTS_2026-07-19.md.

PRE-REGISTERED DESIGN (written before any result was computed)
==============================================================
Strategy under test: delta-neutral funding carry — long 1 unit spot, short 1
unit perp, same venue. Short receives funding when rate > 0 (longs pay shorts,
both venues use this convention).

Capital basis (bankroll honesty): notional N of carry requires 2N capital —
N to buy spot + N collateral on the short at 1x (mission constraint: no
leverage beyond 1x on the short; Binance spot and USDT-M margin are separate
pockets for a retail account). All "$/day" and "APR on capital" figures use 2N.
APR_capital = APR_notional / 2.

Cost model (full open+close cycle, % of carry notional, charged per cycle):
  Binance carry:  spot taker 10bp x2 + perp taker 5bp x2 = 30bp + 5bp
                  spread/slippage => BASE 35bp. Sensitivities: 20bp
                  (BNB discount / maker fills), 50bp (bad fills), 10bp
                  (mission's optimistic figure — shown but NOT the verdict case).
  Cross-venue (perp-perp, 4 legs): Binance perp 5bp x2 + HL taker 4.5bp x2
                  = 19bp + 4bp slippage => BASE 23bp/cycle. Sens: 15bp / 35bp.

Q3 threshold grid (FROZEN — no other variants will be evaluated):
  Signal: trailing 7-day mean funding, annualized, per asset.
  Enter when signal > X, exit when signal < Y (hysteresis).
  Grid: (X,Y) in {(0,0), (5%,0), (5%,5%), (10%,0), (10%,5%)} + always-on.
  Split-half: pick the best variant on H1 (first 365 days of the Binance
  sample, 2024-07-20..2025-07-19), confirm on H2 (2025-07-20..2026-07-19).
  Costs 35bp charged at every entry and exit cycle (35bp covers the full
  round trip; charged once per completed cycle).

Q2 cross-venue: HL hourly rates summed into Binance 8h buckets (overlap
  period, BTC/ETH/SOL). Positioned leg = short the venue with higher trailing
  funding (same 7d trailing signal), earn the realized differential while
  positioned, pay 23bp per flip. Rebalance at 8h / daily / weekly — frozen.

Annualization: Binance 3 events/day x 365 = 1095/yr; HL 8760/yr.
Split-half boundary everywhere: 2025-07-20 00:00 UTC (epoch 1752969600).
"""

from __future__ import annotations

import os
import numpy as np
import pandas as pd

SNAP = os.path.join(os.path.dirname(__file__), "..", "cowork_snapshot", "perps")
H_SPLIT = pd.Timestamp("2025-07-20", tz="UTC")

BINANCE_CYCLE_COSTS = {"base_35bp": 0.0035, "opt_20bp": 0.0020,
                       "pess_50bp": 0.0050, "mission_10bp": 0.0010}
XVENUE_CYCLE_COSTS = {"base_23bp": 0.0023, "opt_15bp": 0.0015, "pess_35bp": 0.0035}
GRID = [("always_on", None, None), ("gt0", 0.00, 0.00), ("gt5_exit0", 0.05, 0.00),
        ("gt5_exit5", 0.05, 0.05), ("gt10_exit0", 0.10, 0.00), ("gt10_exit5", 0.10, 0.05)]

BANKROLLS = [300, 1000, 5000]


def load():
    bf = pd.read_parquet(os.path.join(SNAP, "binance_funding.parquet"))
    hf = pd.read_parquet(os.path.join(SNAP, "hyperliquid_funding.parquet"))
    bb = pd.read_parquet(os.path.join(SNAP, "binance_basis.parquet"))
    for df in (bf, hf, bb):
        df["ts"] = pd.to_datetime(df["ts"], unit="s", utc=True)
    bf = bf.sort_values(["symbol", "ts"]).reset_index(drop=True)
    hf = hf.sort_values(["coin", "ts"]).reset_index(drop=True)
    return bf, hf, bb


def ann_binance(mean_rate_per_event: float) -> float:
    return mean_rate_per_event * 3 * 365


def ann_hl(mean_rate_per_event: float) -> float:
    return mean_rate_per_event * 8760


def dd_stats(cum: pd.Series, ts: pd.Series) -> dict:
    """Max drawdown / time-under-water on a cumulative-return series (capital basis)."""
    peak = cum.cummax()
    dd = cum - peak
    mdd = dd.min()
    under = dd < -1e-12
    # longest under-water stretch in days
    longest, cur_start, longest_span = 0.0, None, (None, None)
    for i in range(len(cum)):
        if under.iloc[i] and cur_start is None:
            cur_start = ts.iloc[i]
        elif not under.iloc[i] and cur_start is not None:
            span = (ts.iloc[i] - cur_start).total_seconds() / 86400
            if span > longest:
                longest, longest_span = span, (cur_start, ts.iloc[i])
            cur_start = None
    if cur_start is not None:
        span = (ts.iloc[-1] - cur_start).total_seconds() / 86400
        if span > longest:
            longest, longest_span = span, (cur_start, ts.iloc[-1])
    pct_under = under.mean()
    return {"max_dd": mdd, "pct_time_under_water": pct_under,
            "longest_under_water_days": longest, "uw_span": longest_span}


# ----------------------------------------------------------------------------
# Q1 — single-venue delta-neutral carry (Binance, full 2y; HL, 1y)
# ----------------------------------------------------------------------------

def q1_binance(bf: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for sym, g in bf.groupby("symbol"):
        g = g.sort_values("ts")
        yrs = (g.ts.iloc[-1] - g.ts.iloc[0]).total_seconds() / (365 * 86400)
        gross_apr_notional = ann_binance(g.rate.mean())
        # always-on net: one 35bp cycle amortized over the whole sample
        net_apr_notional = gross_apr_notional - BINANCE_CYCLE_COSTS["base_35bp"] / yrs
        cum_cap = (g.rate / 2).cumsum()            # capital basis
        d = dd_stats(cum_cap, g.ts.reset_index(drop=True))
        rows.append({
            "symbol": sym, "events": len(g), "years": round(yrs, 2),
            "pct_events_negative": (g.rate < 0).mean(),
            "gross_apr_notional": gross_apr_notional,
            "gross_apr_capital": gross_apr_notional / 2,
            "net_apr_capital_always_on": net_apr_notional / 2,
            "max_dd_capital": d["max_dd"],
            "pct_time_under_water": d["pct_time_under_water"],
            "longest_uw_days": round(d["longest_under_water_days"], 1),
            "uw_span": d["uw_span"],
            "worst_30d_apr": ann_binance(g.rate.rolling(90).mean().min()),
            "best_30d_apr": ann_binance(g.rate.rolling(90).mean().max()),
        })
    return pd.DataFrame(rows).set_index("symbol")


def q1_quarters(bf: pd.DataFrame) -> pd.DataFrame:
    g = bf.copy()
    g["q"] = g.ts.dt.tz_localize(None).dt.to_period("Q")
    out = g.groupby(["symbol", "q"])["rate"].mean().map(ann_binance).unstack(0)
    return out


def q1_portfolio(bf: pd.DataFrame, symbols=None) -> dict:
    g = bf if symbols is None else bf[bf.symbol.isin(symbols)]
    per_event = g.groupby("ts")["rate"].mean().sort_index()  # equal-weight
    yrs = (per_event.index[-1] - per_event.index[0]).total_seconds() / (365 * 86400)
    gross = ann_binance(per_event.mean())
    cum_cap = (per_event / 2).cumsum()
    d = dd_stats(cum_cap.reset_index(drop=True), per_event.index.to_series().reset_index(drop=True))
    return {"gross_apr_notional": gross, "gross_apr_capital": gross / 2,
            "net_apr_capital_always_on": (gross - BINANCE_CYCLE_COSTS["base_35bp"] / yrs) / 2,
            "max_dd_capital": d["max_dd"], "pct_uw": d["pct_time_under_water"],
            "longest_uw_days": d["longest_under_water_days"], "uw_span": d["uw_span"],
            "pct_events_negative": (per_event < 0).mean()}


def q1_hyperliquid(hf: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for coin, g in hf.groupby("coin"):
        g = g.sort_values("ts")
        gross = ann_hl(g.rate.mean())
        cum_cap = (g.rate / 2).cumsum()
        d = dd_stats(cum_cap, g.ts.reset_index(drop=True))
        rows.append({"coin": coin, "events": len(g),
                     "gross_apr_notional": gross, "gross_apr_capital": gross / 2,
                     "pct_events_negative": (g.rate < 0).mean(),
                     "max_dd_capital": d["max_dd"],
                     "pct_time_under_water": d["pct_time_under_water"],
                     "longest_uw_days": round(d["longest_under_water_days"], 1)})
    return pd.DataFrame(rows).set_index("coin")


# ----------------------------------------------------------------------------
# Basis + liquidation honesty
# ----------------------------------------------------------------------------

def basis_stats(bb: pd.DataFrame) -> pd.DataFrame:
    wide = bb.pivot_table(index=["symbol", "ts"], columns="kind", values="close").reset_index()
    wide["basis"] = wide["perp"] / wide["spot"] - 1
    rows = []
    for sym, g in wide.groupby("symbol"):
        g = g.sort_values("ts")
        rows.append({"symbol": sym, "mean_bp": g.basis.mean() * 1e4,
                     "std_bp": g.basis.std() * 1e4,
                     "p5_bp": g.basis.quantile(0.05) * 1e4,
                     "p95_bp": g.basis.quantile(0.95) * 1e4,
                     "worst_1d_widening_bp": g.basis.diff().max() * 1e4})
    return pd.DataFrame(rows).set_index("symbol")


def liquidation_stats(bb: pd.DataFrame) -> pd.DataFrame:
    """Worst rally the short leg had to survive: max forward run-up from any
    daily close within horizons. 1x collateral liquidates ~+100% (less MM)."""
    spot = bb[bb.kind == "spot"].pivot(index="ts", columns="symbol", values="close").sort_index()
    rows = []
    for sym in spot.columns:
        s = spot[sym].dropna()
        out = {"symbol": sym}
        for h in (7, 30, 90):
            fwd_max = s[::-1].rolling(h, min_periods=1).max()[::-1].shift(-1)
            out[f"worst_runup_{h}d"] = (fwd_max / s - 1).max()
        rows.append(out)
    return pd.DataFrame(rows).set_index("symbol")


# ----------------------------------------------------------------------------
# Q3 — threshold variants, split-half (defined before Q2 in code order but
# reported after; frozen grid in GRID)
# ----------------------------------------------------------------------------

def run_threshold(g: pd.DataFrame, enter: float | None, exit_: float | None,
                  cost_cycle: float) -> dict:
    """One asset, one rule. Signal = trailing 7d (21-event) mean funding, annualized,
    lagged one event (no look-ahead). Returns net annualized return on CAPITAL."""
    g = g.sort_values("ts").reset_index(drop=True)
    sig = ann_binance(g.rate.rolling(21).mean()).shift(1)
    if enter is None:
        pos = pd.Series(True, index=g.index)
    else:
        pos = pd.Series(False, index=g.index)
        holding = False
        for i in range(len(g)):
            s = sig.iloc[i]
            if np.isnan(s):
                pos.iloc[i] = holding = False
                continue
            if not holding and s > enter:
                holding = True
            elif holding and s < exit_:
                holding = False
            pos.iloc[i] = holding
    yrs = (g.ts.iloc[-1] - g.ts.iloc[0]).total_seconds() / (365 * 86400)
    gross = (g.rate * pos).sum()
    entries = (pos & ~pos.shift(1, fill_value=False)).sum()
    net = gross - entries * cost_cycle
    return {"net_ann_capital": net / 2 / yrs, "gross_ann_capital": gross / 2 / yrs,
            "pct_in_market": pos.mean(), "cycles": int(entries)}


def q3(bf: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    cost = BINANCE_CYCLE_COSTS["base_35bp"]
    halves = {"H1": bf[bf.ts < H_SPLIT], "H2": bf[bf.ts >= H_SPLIT]}
    out = {}
    for hname, hdf in halves.items():
        rows = []
        for name, enter, exit_ in GRID:
            per_asset = {sym: run_threshold(g, enter, exit_, cost)
                         for sym, g in hdf.groupby("symbol")}
            rows.append({
                "rule": name,
                "portfolio_net_ann_capital": np.mean([v["net_ann_capital"] for v in per_asset.values()]),
                "mean_pct_in_market": np.mean([v["pct_in_market"] for v in per_asset.values()]),
                "total_cycles": sum(v["cycles"] for v in per_asset.values()),
            })
        out[hname] = pd.DataFrame(rows).set_index("rule")
    return out["H1"], out["H2"]


# ----------------------------------------------------------------------------
# Q2 — cross-venue divergence (Binance vs Hyperliquid), overlap period
# ----------------------------------------------------------------------------

def align_venues(bf: pd.DataFrame, hf: pd.DataFrame) -> pd.DataFrame:
    """HL hourly rates summed into the Binance 8h bucket ENDING at each Binance
    funding ts (bucket = (ts-8h, ts])."""
    frames = []
    for coin in ("BTC", "ETH", "SOL"):
        b = bf[bf.symbol == coin + "USDT"][["ts", "rate"]].rename(columns={"rate": "bin"})
        h = hf[hf.coin == coin][["ts", "rate"]].set_index("ts").sort_index()
        h8 = h.rate.resample("8h", label="right", closed="right").sum()
        m = b.merge(h8.rename("hl"), left_on="ts", right_index=True, how="inner")
        m["coin"] = coin
        frames.append(m)
    out = pd.concat(frames).dropna()
    out["div"] = out["bin"] - out["hl"]      # >0: Binance funding richer
    return out


def q2(av: pd.DataFrame) -> dict:
    res = {}
    desc = av.groupby("coin")["div"].agg(["mean", "std",
                                          lambda s: (s.abs() * 1e4).median()])
    desc.columns = ["mean_per8h", "std_per8h", "median_abs_bp_per8h"]
    desc["mean_ann"] = desc["mean_per8h"] * 1095
    res["divergence_desc"] = desc
    for cname, cost in XVENUE_CYCLE_COSTS.items():
        res[f"pct_8h_abs_div_gt_{cname}"] = (av["div"].abs() > cost).mean()
    # strategy: position toward trailing 7d divergence; earn realized div while positioned
    rows = []
    for freq_name, every in (("8h", 1), ("daily", 3), ("weekly", 21)):
        for cname, cost in XVENUE_CYCLE_COSTS.items():
            tot_net, tot_gross, tot_yrs, flips = 0.0, 0.0, 0.0, 0
            for coin, g in av.groupby("coin"):
                g = g.sort_values("ts").reset_index(drop=True)
                sig = g["div"].rolling(21).mean().shift(1)
                side = np.sign(sig)                       # +1: short Binance / long HL
                side = pd.Series(side).where(pd.Series(sig).notna(), 0)
                side = side.iloc[::every].reindex(range(len(g))).ffill().fillna(0)
                pnl = (side * g["div"]).sum()
                nflip = int((side.diff().abs() > 0).sum())
                yrs = (g.ts.iloc[-1] - g.ts.iloc[0]).total_seconds() / (365 * 86400)
                tot_gross += pnl / 2 / yrs
                tot_net += (pnl - nflip * cost) / 2 / yrs
                tot_yrs = yrs
                flips += nflip
            n = av.coin.nunique()
            rows.append({"rebalance": freq_name, "cost": cname,
                         "gross_ann_capital": tot_gross / n,
                         "net_ann_capital": tot_net / n,
                         "flips_per_coin_yr": flips / n / tot_yrs})
    res["strategy"] = pd.DataFrame(rows)
    return res


# ----------------------------------------------------------------------------
# Bankroll math
# ----------------------------------------------------------------------------

def bankroll_table(net_apr_capital: float) -> pd.DataFrame:
    rows = [{"bankroll_usd": b, "usd_per_day": b * net_apr_capital / 365}
            for b in BANKROLLS]
    rows.append({"bankroll_usd": round(365 / net_apr_capital) if net_apr_capital > 0 else np.inf,
                 "usd_per_day": 1.0})
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------
# Supplement — recent-regime venue comparison, concentration, uncertainty
# ----------------------------------------------------------------------------

def block_bootstrap_ci(rates: pd.Series, events_per_year: int, block: int = 21,
                       n: int = 2000, seed: int = 7) -> tuple[float, float, float]:
    """Moving-block bootstrap CI (2.5/97.5%) on annualized mean rate (notional)."""
    rng = np.random.default_rng(seed)
    r = rates.to_numpy()
    nblocks = int(np.ceil(len(r) / block))
    starts_max = len(r) - block
    means = np.empty(n)
    for i in range(n):
        starts = rng.integers(0, starts_max + 1, nblocks)
        sample = np.concatenate([r[s:s + block] for s in starts])[:len(r)]
        means[i] = sample.mean()
    lo, hi = np.quantile(means, [0.025, 0.975])
    return r.mean() * events_per_year, lo * events_per_year, hi * events_per_year


def supplement(bf: pd.DataFrame, hf: pd.DataFrame):
    h2 = bf[bf.ts >= H_SPLIT]
    print("\n#### SUPPLEMENT: last-365d (H2) Binance gross APR notional, per asset")
    print(h2.groupby("symbol")["rate"].mean().map(ann_binance).round(4).to_string())
    print("\n#### SUPPLEMENT: same-window venue comparison, gross APR notional")
    for coin in ("BTC", "ETH", "SOL"):
        b = ann_binance(h2[h2.symbol == coin + "USDT"].rate.mean())
        h = ann_hl(hf[hf.coin == coin].rate.mean())
        print(f"  {coin}: Binance {b:.4%}  vs  Hyperliquid {h:.4%}")
    print("\n#### SUPPLEMENT: feast/famine — share of 2y gross funding earned in top 10% of events")
    for sym, g in bf.groupby("symbol"):
        pos_total = g.rate.sum()
        top = g.rate.nlargest(int(len(g) * 0.10)).sum()
        print(f"  {sym}: top-decile events = {top / pos_total:.1f}x of total net funding" if pos_total > 0
              else f"  {sym}: net funding <= 0")
    print("\n#### SUPPLEMENT: block-bootstrap 95% CI on gross APR (notional), 7d blocks")
    port = bf.groupby("ts")["rate"].mean().sort_index()
    m, lo, hi = block_bootstrap_ci(port, 1095)
    print(f"  Binance all-6 portfolio, 2y: {m:.4%}  [{lo:.4%}, {hi:.4%}]")
    m, lo, hi = block_bootstrap_ci(port[port.index >= H_SPLIT], 1095)
    print(f"  Binance all-6 portfolio, H2 only: {m:.4%}  [{lo:.4%}, {hi:.4%}]")
    for coin in ("BTC", "ETH", "HYPE"):
        s = hf[hf.coin == coin].sort_values("ts").rate
        m, lo, hi = block_bootstrap_ci(s, 8760, block=168)
        print(f"  Hyperliquid {coin}, 1y: {m:.4%}  [{lo:.4%}, {hi:.4%}]")
    print("\n#### SUPPLEMENT: HL bankroll math (net capital APR = gross/2 minus one 35bp cycle/yr)")
    for label, coins in (("HL BTC+ETH", ["BTC", "ETH"]), ("HL HYPE solo", ["HYPE"])):
        g = hf[hf.coin.isin(coins)]
        gross = ann_hl(g.groupby("ts")["rate"].mean().mean())
        net_cap = (gross - BINANCE_CYCLE_COSTS["base_35bp"]) / 2
        print(f"  {label}: gross notional {gross:.4%}, net capital {net_cap:.4%}")
        print(bankroll_table(net_cap).round(3).to_string(index=False))
    print("\n#### SUPPLEMENT: funding persistence (autocorr of daily mean rate, lag 1/7/30d)")
    for sym in ("BTCUSDT", "ETHUSDT"):
        d = bf[bf.symbol == sym].set_index("ts").rate.resample("1D").mean().dropna()
        print(f"  {sym}: {d.autocorr(1):.2f} / {d.autocorr(7):.2f} / {d.autocorr(30):.2f}")


def main():
    pd.set_option("display.width", 200)
    bf, hf, bb = load()
    print("#### Q1 Binance per-asset (2y)")
    q1b = q1_binance(bf)
    print(q1b.round(4).to_string())
    print("\n#### Q1 quarterly gross APR (notional)")
    print(q1_quarters(bf).round(3).to_string())
    def show_port(d):
        for k, v in d.items():
            print(f"  {k}: {round(v, 4) if isinstance(v, (int, float, np.floating)) else v}")
    print("\n#### Q1 portfolio (all 6, equal weight)")
    show_port(q1_portfolio(bf))
    print("\n#### Q1 portfolio (BTC/ETH/SOL only)")
    show_port(q1_portfolio(bf, ["BTCUSDT", "ETHUSDT", "SOLUSDT"]))
    print("\n#### Q1 Hyperliquid per-coin (1y)")
    print(q1_hyperliquid(hf).round(4).to_string())
    print("\n#### Basis stats (perp/spot - 1)")
    print(basis_stats(bb).round(2).to_string())
    print("\n#### Liquidation honesty: worst forward price run-up (short leg risk)")
    print(liquidation_stats(bb).round(3).to_string())
    print("\n#### Q3 threshold grid — H1 (choose here)")
    h1, h2 = q3(bf)
    print(h1.round(4).to_string())
    print("\n#### Q3 threshold grid — H2 (confirm here)")
    print(h2.round(4).to_string())
    print("\n#### Q2 cross-venue (overlap, BTC/ETH/SOL)")
    av = align_venues(bf, hf)
    print(f"aligned 8h buckets: {len(av)}  span: {av.ts.min()} -> {av.ts.max()}")
    r = q2(av)
    print(r["divergence_desc"].round(6).to_string())
    for k, v in r.items():
        if k.startswith("pct_8h"):
            print(f"{k}: {v:.4%}")
    print(r["strategy"].round(4).to_string())
    print("\n#### Bankroll math (uses BTC/ETH/SOL portfolio always-on net, base costs)")
    p = q1_portfolio(bf, ["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    print(bankroll_table(p["net_apr_capital_always_on"]).to_string(index=False))
    print("\n#### Bankroll math (all-6 portfolio)")
    p6 = q1_portfolio(bf)
    print(bankroll_table(p6["net_apr_capital_always_on"]).to_string(index=False))
    print("\n#### Cost sensitivity, always-on all-6 portfolio net APR on capital")
    per_event = bf.groupby("ts")["rate"].mean()
    yrs = (per_event.index[-1] - per_event.index[0]).total_seconds() / (365 * 86400)
    gross = ann_binance(per_event.mean())
    for cname, c in BINANCE_CYCLE_COSTS.items():
        print(f"  {cname}: {(gross - c / yrs) / 2:.4%}")
    supplement(bf, hf)


if __name__ == "__main__":
    main()
