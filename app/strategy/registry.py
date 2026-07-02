"""Static strategy registry (03 §6). No dynamic import from user input."""

from app.strategy.base import BaseStrategy
from app.strategy.liquidity_sweep import LiquiditySweepStrategy

_REGISTRY: dict[str, BaseStrategy] = {
    LiquiditySweepStrategy.code: LiquiditySweepStrategy(),
}


def get_strategy(code: str) -> BaseStrategy | None:
    return _REGISTRY.get(code)
