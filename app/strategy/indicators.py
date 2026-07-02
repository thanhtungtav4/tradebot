"""Pure indicator helpers: EMA and session label (03 §3, §5)."""

from datetime import datetime
from decimal import Decimal

# LONDON > NEWYORK > TOKYO > SYDNEY when overlapping (03 §3 session windows).
_SESSIONS = [
    ("LONDON", 7, 16),
    ("NEWYORK", 12, 21),
    ("TOKYO", 0, 9),
    ("SYDNEY", 21, 6),  # wraps midnight
]


def ema(values: list[Decimal], period: int) -> Decimal | None:
    """Exponential moving average. Needs >= period values; else None.

    Seeded with the SMA of the first `period` values, then standard EMA recursion.
    """
    if period <= 0 or len(values) < period:
        return None
    k = Decimal(2) / Decimal(period + 1)
    seed = sum(values[:period]) / Decimal(period)
    e = seed
    for v in values[period:]:
        e = v * k + e * (Decimal(1) - k)
    return e


def session_label(candle_time: datetime) -> str:
    """Return the priority session for a UTC candle time."""
    hour = candle_time.hour
    for name, start, end in _SESSIONS:
        in_window = start <= hour < end if start < end else (hour >= start or hour < end)
        if in_window:
            return name
    return "SYDNEY"
