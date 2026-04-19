"""
Daily loss circuit breaker for live trading.

Tracks realized P&L since midnight UTC. If the day's losses exceed the
configured limit, the bot is halted and must be manually reset.

Usage in the live loop:
    from src.bot.circuit_breaker import CircuitBreaker
    cb = CircuitBreaker()   # reads LIVE_MAX_DAILY_LOSS_USD from .env

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

Thread-safety: all public methods are protected by a threading.Lock so the
circuit breaker can safely be shared across market threads (Finding 2.B).
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

STATE_FILE = Path("output/5m_live/circuit_breaker.json")

# Default limit — override via .env LIVE_MAX_DAILY_LOSS_USD (Finding 6.B)
_DEFAULT_MAX_LOSS = float(os.environ.get("LIVE_MAX_DAILY_LOSS_USD", "50.0"))


def _today_utc() -> str:
    """Return today's date as YYYY-MM-DD (UTC)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class CircuitBreaker:
    """
    Halts new entries when daily losses exceed max_daily_loss_usd.
    Resets automatically at UTC midnight.
    Thread-safe: safe to share across multiple market threads.
    """

    def __init__(self, max_daily_loss_usd: float | None = None) -> None:
        self.max_daily_loss_usd = max_daily_loss_usd if max_daily_loss_usd is not None else _DEFAULT_MAX_LOSS
        # Finding 5 (HIGH): warn if limit is too high to provide meaningful protection
        if self.max_daily_loss_usd > 40:
            print(
                f"[CIRCUIT BREAKER] WARNING: max_daily_loss_usd={self.max_daily_loss_usd} is very high. "
                f"Set LIVE_MAX_DAILY_LOSS_USD to ~20-30% of account equity to get meaningful protection."
            )
        self._lock = threading.Lock()
        self._load()

    # ── Persistence ────────────────────────────────────────────────────────────

    def _load(self) -> None:
        """Load state from disk. Must be called with lock held (or from __init__)."""
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        today = _today_utc()
        if STATE_FILE.exists():
            try:
                data = json.loads(STATE_FILE.read_text())
                if data.get("date") == today:
                    self._date        = today
                    self._daily_pnl   = float(data.get("daily_pnl", 0.0))
                    self._trade_count = int(data.get("trade_count", 0))
                    self._tripped     = bool(data.get("tripped", False))
                    return
                # Different date — new day, fall through to reset
            except Exception:
                # Corrupt file — treat as tripped (safe default) rather than
                # resetting the counter to 0, which could allow unlimited losses
                # on the same day after a crash. (Finding 6.A)
                print(
                    "[CIRCUIT BREAKER] WARNING: corrupt state file — treating as TRIPPED. "
                    "Delete output/5m_live/circuit_breaker.json to reset."
                )
                self._date        = today
                self._daily_pnl   = 0.0
                self._trade_count = 0
                self._tripped     = True
                self._save()
                return
        # Missing file or new day — fresh start
        self._date        = today
        self._daily_pnl   = 0.0
        self._trade_count = 0
        self._tripped     = False
        self._save()

    def _save(self) -> None:
        """Write state to disk. Must be called with lock held."""
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
        with self._lock:
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
        with self._lock:
            if _today_utc() != self._date:
                self._load()   # new day → auto-reset
            return not self._tripped

    def is_soft_stop(self, threshold_usd: float) -> bool:
        """
        Soft daily-loss gate (Cowork 2026-04-19 Strategy #8).
        Returns True when today's realised P&L is at or below ``-abs(threshold_usd)``
        **without** tripping the hard circuit breaker. Callers should block new
        entries when this returns True; the bot continues to manage open positions.

        threshold_usd: e.g. 10.0 → gate at -$10. Auto-resets at UTC midnight via
        the existing _load() path.
        """
        with self._lock:
            if _today_utc() != self._date:
                self._load()
            return self._daily_pnl <= -abs(float(threshold_usd))

    def status(self) -> str:
        with self._lock:
            tripped = self._tripped
            pnl     = self._daily_pnl
            count   = self._trade_count
        return (
            f"[CIRCUIT BREAKER] {'OPEN' if not tripped else 'TRIPPED'} | "
            f"today P&L=${pnl:+.2f} | "
            f"limit=-${self.max_daily_loss_usd:.2f} | "
            f"trades={count} | "
            f"resets at UTC midnight"
        )
