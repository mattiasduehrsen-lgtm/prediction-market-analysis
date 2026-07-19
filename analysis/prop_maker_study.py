"""Prop-maker seat study — who collects the prop takers' bleed? (2026-07-19)

The GRID re-fit measured prop TAKERS losing -9%..-61% at executable quotes.
That bleed is someone's maker income. The data-api tape is taker-only (verified:
no tx duplicates), so maker WALLETS are unobservable — but aggregate maker PnL
is EXACTLY observable: every trade has one maker and one taker, so per market

    maker_gross_pnl = -(taker aggregate cash + taker net inventory x payout)

with no leakage (mint/redeem happens off-book; each book trade still mirrors).

Measures, per prop class and for series (comparison), GRID-era CS2/LoL:
  - aggregate taker net PnL at resolution -> maker gross income
  - est. taker fees (sports curve: fee = shares x 0.03 x p^2 x (1-p), the form
    that peaks ~0.75% of notional at p=0.5) and the 25% maker rebate pool
  - maker seat run-rate $/day + weekly trend (is the seat shrinking?)
  - taker-side wallet concentration (takers ARE identified)

Output: printed report + output/wallet_study/prop_maker_report.txt
Run (dev, tapes local): .venv\\Scripts\\python.exe -u analysis/prop_maker_study.py
"""
import re
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "analysis"))
from tape_backfill import prop_universe, universe, TR, RES

OUT = ROOT / "output" / "wallet_study"
OUT.mkdir(parents=True, exist_ok=True)


def classify(slug):
    s = slug or ""
    if "handicap" in s: return "handicap"
    if "round-total" in s or "total-games" in s or "kill-over" in s or "kill-under" in s: return "totals"
    if "kill" in s: return "kills"
    if "first-" in s: return "firsts"
    if re.search(r"game\d+$", s): return "map_winner"
    if re.search(r"-(slay|destroy|baron|dragon|inhibitor|ace)", s): return "occurrence"
    return "other_prop"


def market_pnl(fp, winning):
    """(taker_cash_at_resolution, notional, est_fees, taker_flows_by_wallet, n_trades)
    winning: winning outcome name (lower) or None -> skip."""
    t = pd.read_parquet(fp)
    if t.empty:
        return None
    for c in ("ts", "price", "size"):
        t[c] = pd.to_numeric(t[c], errors="coerce")
    t = t.dropna(subset=["price", "size", "outcome"])
    # ~2% of rows are exact duplicates (offset-pagination shift during fetch)
    t = t.drop_duplicates()
    if t.empty:
        return None
    out_l = t.outcome.astype(str).str.strip().str.lower()
    if winning is None:
        # terminal-price fallback (validated 1.000 agreement earlier): last
        # trade >0.9 on an outcome, or <0.1 implies the complement won
        last = t.sort_values("ts").iloc[-1]
        lp, lo = float(last.price), str(last.outcome).strip().lower()
        outs = sorted(out_l.unique())
        if lp > 0.9:
            winning = lo
        elif lp < 0.1 and len(outs) == 2:
            winning = next(o for o in outs if o != lo)
        else:
            return None
    # TRADING BAND ONLY (0.03 <= p <= 0.97): the maker's real business.
    # Settlement-band prints (0.999 mega-blocks on decided markets) are a
    # different activity (exit liquidity on near-certainties) whose giant
    # notionals swamp every aggregate and amplify any resolution-label error
    # by 5 figures per market. Measured separately as settle_notional.
    band = (t.price >= 0.03) & (t.price <= 0.97)
    settle_notional = float((t.price * t["size"])[~band].sum())
    t = t[band]
    out_l = out_l[band]
    if t.empty:
        return None
    buy = t.side.astype(str).str.upper() == "BUY"
    sgn = np.where(buy, 1.0, -1.0)                    # taker position delta sign
    cash = -(sgn * t.price.to_numpy() * t["size"].to_numpy())   # taker cash/row
    win_mask = (out_l == winning).to_numpy()
    payout = sgn * t["size"].to_numpy() * win_mask    # resolution value of delta
    pnl_rows = cash + payout
    fees = (t["size"] * 0.03 * t.price**2 * (1 - t.price)).to_numpy()
    by_wallet = defaultdict(float)
    w = t.wallet.astype(str).str.lower().to_numpy() if "wallet" in t.columns else None
    if w is not None:
        for i in range(len(t)):
            by_wallet[w[i]] += pnl_rows[i]
    notional = float((t.price * t["size"]).sum())
    return float(pnl_rows.sum()), notional, float(fees.sum()), by_wallet, len(t), settle_notional


def run(uni, label, win_map):
    rows, wallets = [], defaultdict(float)
    n_no_res = 0
    for r in uni.itertuples(index=False):
        fp = TR / f"{r.condition_id}.parquet"
        if not fp.exists():
            continue
        wn = win_map.get(r.slug)
        res = market_pnl(fp, str(wn).strip().lower() if isinstance(wn, str) else None)
        if res is None:
            n_no_res += 1
            continue
        taker_pnl, notional, fees, bw, n_tr, settle_no = res
        cls = "series" if label == "series" else classify(r.slug)
        rows.append(dict(slug=r.slug, game=r.game, cls=cls, gs=r.gs,
                         taker_pnl=taker_pnl, maker_gross=-taker_pnl,
                         notional=notional, fees=fees, n_trades=n_tr,
                         settle_notional=settle_no))
        for k, v in bw.items():
            wallets[k] += v
    return pd.DataFrame(rows), wallets, n_no_res


def main():
    res = pd.read_parquet(RES)
    res = res[res.winning_outcome.notna()][["slug", "winning_outcome"]].drop_duplicates("slug")
    win_map = dict(zip(res.slug, res.winning_outcome))
    lines = []
    P = lines.append

    props, pw, skip_p = run(prop_universe(), "props", win_map)
    series, sw, skip_s = run(universe(), "series", win_map)
    P(f"markets scored: props={len(props)} (unresolvable {skip_p}), "
      f"series={len(series)} (unresolvable {skip_s})")
    days = (max(props.gs.max(), series.gs.max()) - min(props.gs.min(), series.gs.min())).days + 1
    P(f"span: {days} days (GRID era)")

    P(f"settlement-band notional excluded (p<0.03 or >0.97): "
      f"props ${props.settle_notional.sum():,.0f}, series ${series.settle_notional.sum():,.0f}")
    P("\nMAKER SEAT BY SURFACE — TRADING BAND 0.03–0.97 ONLY "
      "(aggregate, gross of fees; rebate = 25% of taker fees):")
    P(f"{'class':12} {'mkts':>5} {'trades':>7} {'taker notional':>15} "
      f"{'maker gross':>12} {'est fees':>9} {'rebate':>8} {'maker $/day':>11} {'gross margin':>12}")
    for cls, g in pd.concat([props, series]).groupby("cls"):
        mg, fe, no = g.maker_gross.sum(), g.fees.sum(), g.notional.sum()
        P(f"{cls:12} {len(g):5d} {g.n_trades.sum():7d} ${no:>13,.0f} "
          f"${mg:>10,.0f} ${fe:>7,.0f} ${fe*0.25:>6,.0f} ${(mg + fe*0.25)/days:>9,.2f} "
          f"{mg/no if no else 0:>11.1%}")
    tot_m = props.maker_gross.sum(); tot_f = props.fees.sum()
    P(f"\nPROP maker seat TOTAL: gross ${tot_m:,.0f} + rebates ${tot_f*0.25:,.0f} "
      f"over {days}d = ${(tot_m + tot_f*0.25)/days:,.2f}/day")
    P(f"SERIES maker seat (comparison): ${(series.maker_gross.sum() + series.fees.sum()*0.25)/days:,.2f}/day")

    P("\nweekly trend (prop maker gross $):")
    props["week"] = props.gs.dt.strftime("%G-W%V")
    P(props.groupby("week").maker_gross.sum().round(0).to_string())

    P("\ntaker-side concentration (props; takers are identified):")
    ws = pd.Series(pw).sort_values()
    P(f"  unique taker wallets: {len(ws):,}; losers {int((ws < 0).sum()):,} / winners {int((ws > 0).sum()):,}")
    P(f"  top-5 largest taker LOSSES: {[round(x) for x in ws.head(5)]}")
    P(f"  top-5 largest taker WINS:   {[round(x) for x in ws.tail(5)]}")
    P(f"  share of total taker bleed from top-10 losers: "
      f"{ws.head(10).sum() / ws[ws < 0].sum():.0%}" if (ws < 0).any() else "-")

    P("\nCAVEATS: maker identity unobservable in this feed (aggregate exact via "
      "per-trade mirror); fees estimated from the published sports curve, not "
      "per-trade fields; unresolvable markets skipped; competing for this seat "
      "was NOT validated - audit row 5 (naive makers lose) and the sim's "
      "adverse-selection result stand as warnings.")
    txt = "\n".join(lines)
    print(txt)
    (OUT / "prop_maker_report.txt").write_text(txt, encoding="utf-8")


if __name__ == "__main__":
    main()
