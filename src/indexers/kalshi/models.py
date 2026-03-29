import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


def parse_datetime(val: str) -> datetime:
    val = val.replace("Z", "+00:00")
    # Normalize microseconds to 6 digits
    match = re.match(r"(.+\.\d+)(\+.+)", val)
    if match:
        base, tz = match.groups()
        parts = base.split(".")
        if len(parts) == 2:
            micros = parts[1].ljust(6, "0")[:6]
            val = f"{parts[0]}.{micros}{tz}"
    return datetime.fromisoformat(val)


@dataclass
class Trade:
    trade_id: str
    ticker: str
    count: int
    yes_price: Optional[int]
    no_price: Optional[int]
    taker_side: str
    created_time: datetime

    @classmethod
    def from_dict(cls, data: dict) -> "Trade":
        return cls(
            trade_id=data["trade_id"],
            ticker=data["ticker"],
            count=data.get("count", 0),
            yes_price=data.get("yes_price"),
            no_price=data.get("no_price"),
            taker_side=data.get("taker_side", ""),
            created_time=parse_datetime(data["created_time"]),
        )


@dataclass
class Market:
    ticker: str
    event_ticker: str
    market_type: str
    title: str
    yes_sub_title: str
    no_sub_title: str
    status: str
    yes_bid: Optional[int]
    yes_ask: Optional[int]
    no_bid: Optional[int]
    no_ask: Optional[int]
    last_price: Optional[int]
    volume: int
    volume_24h: int
    open_interest: int
    result: str
    created_time: Optional[datetime]
    open_time: Optional[datetime]
    close_time: Optional[datetime]

    @classmethod
    def from_dict(cls, data: dict) -> "Market":
        def parse_time(val: Optional[str]) -> Optional[datetime]:
            if not val:
                return None
            return parse_datetime(val)

        def _price(key: str, dollars_key: str) -> Optional[float]:
            """Read price from integer cents field or fallback to dollars string field."""
            v = data.get(key)
            if v is not None:
                try:
                    return float(v) / 100.0
                except (TypeError, ValueError):
                    pass
            d = data.get(dollars_key)
            if d is not None:
                try:
                    return float(d)
                except (TypeError, ValueError):
                    pass
            return None

        return cls(
            ticker=data["ticker"],
            event_ticker=data["event_ticker"],
            market_type=data.get("market_type", "binary"),
            title=data.get("title", ""),
            yes_sub_title=data.get("yes_sub_title", ""),
            no_sub_title=data.get("no_sub_title", ""),
            status=data["status"],
            yes_bid=_price("yes_bid", "yes_bid_dollars"),
            yes_ask=_price("yes_ask", "yes_ask_dollars"),
            no_bid=_price("no_bid", "no_bid_dollars"),
            no_ask=_price("no_ask", "no_ask_dollars"),
            last_price=_price("last_price", "last_price_dollars"),
            volume=data.get("volume", 0),
            volume_24h=data.get("volume_24h", 0),
            open_interest=data.get("open_interest", 0),
            result=data.get("result", ""),
            created_time=parse_time(data.get("created_time")),
            open_time=parse_time(data.get("open_time")),
            close_time=parse_time(data.get("close_time")),
        )
