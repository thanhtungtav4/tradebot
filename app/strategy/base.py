"""Strategy plugin interface (03 §2)."""

from app.strategy.types import SignalCandidate, StrategyContext


class BaseStrategy:
    code: str
    name: str
    required_timeframes: list[str]
    trigger_timeframes: list[str]
    # Metadata cho UI catalog + auto-guide TradingView (đợt 1).
    tagline: str
    description: str
    recommended_symbols: list[str]
    style: str  # "SWING" | "INTRADAY" | "SCALP"

    def detect(self, context: StrategyContext) -> list[SignalCandidate]:
        raise NotImplementedError

    def lookback(self, timeframe: str) -> int:
        """Minimum closed candles required for the given timeframe."""
        raise NotImplementedError
