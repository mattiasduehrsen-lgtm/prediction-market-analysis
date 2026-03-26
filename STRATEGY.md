# Polymarket Trading Bot — Strategy & Algorithm

---

## Overview

This bot automatically trades on Polymarket, a prediction market platform where you bet on the probability of real-world events. Every market has a price between 0 and 1 (0¢ to $1.00) representing the market's implied probability that something happens.

The bot runs every 15 minutes, collects fresh data, finds markets where prices have been trending in a consistent direction, and places bets when the signal is strong enough.

---

## Data Sources

The bot pulls from three sources every cycle:

| Source | What it provides |
|---|---|
| **Polymarket Gamma API** | Top 1,000 active markets with current prices and liquidity |
| **Polymarket CLOB API** | 6 hours of minute-by-minute price history for the top 100 markets |
| **Kalshi API** | Equivalent markets from a competing exchange used as a second opinion |

---

## The Core Signal — Price Momentum

The main question the bot asks is:

> **Has this market's price been consistently moving in one direction over the last 6 hours?**

It answers this by splitting the 6-hour price history in half:

- **Early VWAP** — average price from 6 hours ago to 3 hours ago
- **Late VWAP** — average price from 3 hours ago to now
- **Momentum = Late VWAP − Early VWAP**

A positive number means prices have been rising. The bot only buys rising markets.

**Example:** Italy qualifying for the 2026 FIFA World Cup had a momentum of +0.041. The average price in the last 3 hours was 4 cents higher than the 3 hours before that — a consistent upward trend worth betting on.

---

## Secondary Signal — VWAP Edge

Alongside momentum, the bot calculates:

**Edge = Recent VWAP − Current Market Price**

If the average price people paid recently is higher than what the market currently shows, it means buyers have been pushing prices up and the market hasn't fully caught up yet. A positive edge is a buy signal.

---

## Conviction Score

Each signal gets a conviction score from 0–100% that determines how much money to bet:

| Factor | Weight | What it measures |
|---|---|---|
| Edge size | 30% | How large the price gap is |
| Edge ratio | 20% | Edge relative to the price level |
| Buy flow | 20% | What % of recent trades were buys |
| Volume | 20% | How much money has been trading |
| Freshness | 10% | How recently the last trade happened |

**Position sizing:**
- 100% conviction → $100 bet (maximum)
- 50% conviction → $62.50 bet
- 0% conviction → $25 bet (minimum)

---

## Entry Filters

Before buying, every signal must pass all of these checks:

| Filter | Value | Reason |
|---|---|---|
| Price range | 10¢ – 90¢ | Avoid near-settled markets with no upside |
| Minimum liquidity | $100 | Enough depth to enter and exit cleanly |
| Market status | Active, not expired | Don't trade dead markets |
| Time to expiry | At least 2 hours | Avoid markets about to resolve |
| No conflicting position | Must not already hold Yes or No on same market | Prevents betting both sides |
| Kalshi agreement | Kalshi must not disagree | Cross-market confirmation |

---

## Exit Rules

The bot exits positions for six reasons, checked in this order:

| Reason | Trigger | Purpose |
|---|---|---|
| **Take profit** | Price up +15% from entry | Lock in gains |
| **Stop loss** | Price down -12% from entry | Cut losses quickly |
| **Trailing stop** | Price drops 12% from its peak | Protect gains if market reverses |
| **Momentum reversal** | Momentum flips negative | The trend driving the bet is gone |
| **Edge reversal** | Edge drops below -1% | Market moving against the position |
| **Max hold** | Position held 24 hours | Don't hold indefinitely |

---

## What the Results Tell Us

After the first 8 closed trades:

| Trade | Side | Result | Reason |
|---|---|---|---|
| SGA NBA MVP | No | +$15.57 | Strong momentum, clean take-profit |
| Real Madrid win La Liga | Yes | +$4.49 | Consistent buying pressure |
| Barcelona win La Liga | No | +$4.19 | Consistent buying pressure |
| Hungary PM — Péter Magyar | No | +$2.53 | Edge reversal exit |
| Netanyahu out by 2026 | No | +$0.99 | Max hold exit |
| Italy World Cup | Yes | +$6.83 | Momentum correctly identified |
| Italy World Cup | No | -$11.34 | Wrong side of momentum — stop loss |
| OKC Thunder NBA Finals | Yes | -$4.86 | No momentum, held to max hold time |

**Win rate: 75% (6W / 2L)**

### Lessons from the losses

**Italy No (-$11.34):** The bot entered the "No" side of a market that was actually moving toward "Yes." The momentum signal correctly identified the Yes trend, but an earlier version of the bot could enter both sides of the same market. The anti-conflict rule now prevents this — the bot will never hold Yes and No on the same market simultaneously.

**OKC Thunder (-$4.86):** No momentum, no real edge — the position just sat flat until the 24-hour max hold triggered. The momentum reversal exit now catches these earlier by exiting as soon as the trend disappears rather than waiting the full 24 hours.

---

## Why This Has Edge Over Random Betting

A random bettor on Polymarket breaks even at 50% win rate. This bot looks for three conditions that together indicate the market is mispriced:

1. **Price has been trending** (momentum signal) — markets don't always instantly reflect new information. A consistent 6-hour trend suggests real money is flowing in for a reason.

2. **Recent buyers paid more than the current price** (VWAP edge) — if sophisticated participants have been buying at higher prices, the current price may be lagging.

3. **A second exchange agrees** (Kalshi signal) — if Kalshi is pricing the same event higher than Polymarket, it suggests Polymarket is underpriced.

When all three align, the probability of the bet being correct is higher than what the market price implies. That gap between true probability and market price is the edge.

---

## Current Status

| Metric | Value |
|---|---|
| Starting capital | $1,000 (paper) |
| Current equity | $1,018 |
| Realized profit | $18.39 |
| Closed trades | 8 |
| Win rate | 75% |
| Target before going live | 30–50 closed trades, sustained 60%+ win rate |

The strategy is showing early promise but needs more data before committing real money. 30–50 closed trades is the minimum sample size to determine whether the win rate is skill or luck.
