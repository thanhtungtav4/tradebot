"""Strategy plugin interface (03 §2)."""

from app.strategy.types import SignalCandidate, StrategyContext


class BaseStrategy:
    code: str
    name: str
    required_timeframes: list[str]
    trigger_timeframes: list[str]

    def detect(self, context: StrategyContext) -> list[SignalCandidate]:
        raise NotImplementedError

    def lookback(self, timeframe: str) -> int:
        """Minimum closed candles required for the given timeframe."""
        raise NotImplementedError
