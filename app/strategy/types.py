"""Strategy domain types + reject/event constants (03, 04 specs)."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class Candle:
    """A closed OHLC candle. Prices are Decimal."""

    candle_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal | None = None

    @property
    def is_bullish(self) -> bool:
        return self.close > self.open

    @property
    def is_bearish(self) -> bool:
        return self.close < self.open

    @property
    def body(self) -> Decimal:
        return abs(self.close - self.open)

    @property
    def range(self) -> Decimal:
        return self.high - self.low


@dataclass
class StrategyContext:
    symbol: str
    trigger_timeframe: str
    timeframes: dict[str, list[Candle]]  # {"M15": [...], "H1": [...]}
    session: str | None
    spread: Decimal | None
    strategy_config: dict
    symbol_config: dict  # point_size, sl_buffer_points, etc.

    @property
    def latest_closed_candle_time(self) -> datetime | None:
        m15 = self.timeframes.get(self.trigger_timeframe) or []
        return m15[-1].candle_time if m15 else None


@dataclass
class SignalCandidate:
    strategy_code: str
    symbol: str
    timeframe: str
    action: str  # BUY | SELL
    entry: Decimal
    sl: Decimal
    tp: list[Decimal]
    risk_reward: Decimal
    confidence: int
    reason: list[str]
    invalid_if: str
    source_candle_time: datetime
    metadata: dict = field(default_factory=dict)


class RejectCode:
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
    INSUFFICIENT_TREND_DATA = "INSUFFICIENT_TREND_DATA"
    MISSING_PRICE_FIELDS = "MISSING_PRICE_FIELDS"
    RR_TOO_LOW = "RR_TOO_LOW"
    SPREAD_TOO_HIGH = "SPREAD_TOO_HIGH"
    DATA_STALE = "DATA_STALE"
    DUPLICATE = "DUPLICATE"
    INVALID_RR_MATH = "INVALID_RR_MATH"


class EventType:
    SIGNAL_CREATED = "SIGNAL_CREATED"
    SIGNAL_REJECTED = "SIGNAL_REJECTED"
    SIGNAL_APPROVED = "SIGNAL_APPROVED"
    DUPLICATE_SKIPPED = "DUPLICATE_SKIPPED"
    WARMUP_SKIPPED = "WARMUP_SKIPPED"
    SIGNAL_STATUS_UPDATED = "SIGNAL_STATUS_UPDATED"
