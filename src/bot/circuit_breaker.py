"""
Daily loss circuit breaker for live trading.

Tracks realized P&L since midnight UTC. If the day's losses exceed the
configured limit, the bot is halted and must be manually reset.

Usage in the live loop:
    from src.bot.circuit_breaker import CircuitBreaker
    cb = CircuitBreaker(max_daily_loss_usd=50.0)

    # After each closed trade:
    cb.record_trade(pnl_usd)

    # Before each new entry:
    if cb.is_open():
        place_entry(...)
    else:
        print(cb.status())   # prints reason and today's P&L
        # do not enter — loop continues to check exits on open positions

State is persisted to output/5m_live/circuit_breaker.json so a restart
does not reset the daily counter.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

STATE_FILE = Path("output/5m_live/circuit_breaker.json")


def _today_utc() -> str:
    """Return today's date as YYYY-MM-DD (UTC)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class CircuitBreaker:
    """
    Halts new entries when daily losses exceed max_daily_loss_usd.
    Resets automatically at UTC midnight.
    """

    def __init__(self, max_daily_loss_usd: float = 50.0) -> None:
        self.max_daily_loss_usd = max_daily_loss_usd
        self._load()

    # ── Persistence ────────────────────────────────────────────────────────────

    def _load(self) -> None:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        today = _today_utc()
        if STATE_FILE.exists():
            try:
                data = json.loads(STATE_FILE.read_text())
                if data.get("date") == today:
                    self._date       = today
                    self._daily_pnl  = float(data.get("daily_pnl", 0.0))
                    self._trade_count = int(data.get("trade_count", 0))
                    self._tripped    = bool(data.get("tripped", False))
                    return
            except Exception:
                pass
        # New day or corrupt file — reset
        self._date        = today
        self._daily_pnl   = 0.0
        self._trade_count = 0
        self._tripped     = False
        self._save()

    def _save(self) -> None:
        STATE_FILE.write_text(json.dumps({
            "date":        self._date,
            "daily_pnl":   round(self._daily_pnl, 4),
            "trade_count": self._trade_count,
            "tripped":     self._tripped,
            "limit":       self.max_daily_loss_usd,
            "updated_at":  time.time(),
        }, indent=2))

    # ── Public API ─────────────────────────────────────────────────────────────

    def record_trade(self, pnl_usd: float) -> None:
        """Call after every closed trade. Updates daily P&L and trips if limit hit."""
        # Auto-reset on new day
        if _today_utc() != self._date:
            self._load()

        self._daily_pnl   += pnl_usd
        self._trade_count += 1

        if self._daily_pnl <= -abs(self.max_daily_loss_usd):
            if not self._tripped:
                self._tripped = True
                print(
                    f"\n[CIRCUIT BREAKER] TRIPPED — daily loss ${self._daily_pnl:.2f} "
                    f"exceeds limit -${self.max_daily_loss_usd:.2f}. "
                    f"No new entries until UTC midnight.\n"
                )
        self._save()

    def is_open(self) -> bool:
        """True = safe to enter new trades. False = halted."""
        if _today_utc() != self._date:
            self._load()   # new day → auto-reset
        return not self._tripped

    def status(self) -> str:
        return (
            f"[CIRCUIT BREAKER] {'OPEN' if self.is_open() else 'TRIPPED'} | "
            f"today P&L=${self._daily_pnl:+.2f} | "
            f"limit=-${self.max_daily_loss_usd:.2f} | "
            f"trades={self._trade_count} | "
            f"resets at UTC midnight"
        )
