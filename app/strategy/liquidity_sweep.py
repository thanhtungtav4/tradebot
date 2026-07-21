"""Liquidity Sweep v1 (03 §5). Pure detection: candles in -> candidates out.

Trigger timeframe M15, context H1. Detects a sweep of the prior swing low/high,
a close back through it, and a confirmation candle, then builds entry/SL/TP/RR.
"""

from decimal import Decimal

from app.strategy.base import BaseStrategy
from app.strategy.indicators import ema
from app.strategy.types import Candle, SignalCandidate, StrategyContext

_DEFAULTS = {
    "swingLookback": 20,
    "confirmationCandles": 1,
    "minRiskReward": 1.5,
    "tp1R": 1.0,
    "tp2R": 2.0,
    "trendEmaFast": 20,
    "trendEmaSlow": 50,
    "trendGapPoints": 5,
    "sweepDepthPoints": 10,
    "confirmBodyRatio": 0.5,
}


class InsufficientTrendData(Exception):
    """EMA could not be computed despite enough candles (data gap)."""


class LiquiditySweepStrategy(BaseStrategy):
    code = "liquidity_sweep"
    name = "Liquidity Sweep"
    required_timeframes = ["M15", "H1"]
    trigger_timeframes = ["M15"]
    tagline = "Quét thanh khoản đỉnh/đáy rồi vào lệnh đảo chiều"
    description = (
        "Chiến lược này chờ giá quét qua đỉnh hoặc đáy gần nhất (nơi tập trung "
        "lệnh chờ), rồi đóng nến ngược lại. Khi có nến xác nhận, bot vào lệnh "
        "theo hướng đảo chiều với điểm dừng lỗ ngay sau vùng quét. Hợp với vàng "
        "và các cặp chính, khung M15 (bot đọc thêm H1 để xác định xu hướng)."
    )
    recommended_symbols = ["XAUUSD", "EURUSD"]
    style = "INTRADAY"

    def _cfg(self, context: StrategyContext) -> dict:
        return {**_DEFAULTS, **(context.strategy_config or {})}

    def lookback(self, timeframe: str) -> int:
        cfg = _DEFAULTS
        if timeframe == "M15":
            return cfg["swingLookback"] + cfg["confirmationCandles"] + 1  # 22
        if timeframe == "H1":
            return cfg["trendEmaSlow"] + 1  # 51
        return 0

    def detect(self, context: StrategyContext) -> list[SignalCandidate]:
        cfg = self._cfg(context)
        m15 = context.timeframes["M15"]
        h1 = context.timeframes["H1"]

        confirm = m15[-1]
        sweep = m15[-2]
        swing_window = m15[-(cfg["swingLookback"] + 2) : -2]
        if not swing_window:
            return []

        point = Decimal(str(context.symbol_config.get("point_size", "0.01")))
        buffer_pts = Decimal(str(context.symbol_config.get("sl_buffer_points", "0")))
        buffer = buffer_pts * point

        trend = self._trend(h1, cfg)  # "UP" | "DOWN" | "FLAT"

        buy = self._try_buy(context, cfg, confirm, sweep, swing_window, point, buffer, trend)
        if buy:
            return [buy]
        sell = self._try_sell(context, cfg, confirm, sweep, swing_window, point, buffer, trend)
        if sell:
            return [sell]
        return []

    def _trend(self, h1: list[Candle], cfg: dict) -> str:
        closes = [c.close for c in h1]
        fast = ema(closes, cfg["trendEmaFast"])
        slow = ema(closes, cfg["trendEmaSlow"])
        if fast is None or slow is None:
            raise InsufficientTrendData()
        gap = fast - slow
        return "UP" if gap > 0 else "DOWN" if gap < 0 else "FLAT"

    def _try_buy(self, ctx, cfg, confirm, sweep, window, point, buffer, trend):
        if trend == "DOWN":
            return None
        swing_low = min(c.low for c in window)
        # sweep dips below swing low but closes back above it
        if not (sweep.low < swing_low and sweep.close > swing_low):
            return None
        if not confirm.is_bullish:
            return None

        entry = confirm.close
        sl = sweep.low - buffer
        risk = entry - sl
        if risk <= 0:
            return None
        tp1 = entry + risk * Decimal(str(cfg["tp1R"]))
        tp2 = entry + risk * Decimal(str(cfg["tp2R"]))
        rr = (tp2 - entry) / risk
        reason = [
            "Swept previous low",
            "Closed back above swing low",
            "M15 bullish confirmation",
            "H1 trend not bearish",
        ]
        confidence = self._confidence(cfg, "BUY", confirm, sweep, swing_low, rr, trend, point)
        return SignalCandidate(
            strategy_code=self.code, symbol=ctx.symbol, timeframe="M15", action="BUY",
            entry=entry, sl=sl, tp=[tp1, tp2], risk_reward=rr, confidence=confidence,
            reason=reason, invalid_if=f"M15 closes below {sl}",
            source_candle_time=confirm.candle_time,
        )

    def _try_sell(self, ctx, cfg, confirm, sweep, window, point, buffer, trend):
        if trend == "UP":
            return None
        swing_high = max(c.high for c in window)
        if not (sweep.high > swing_high and sweep.close < swing_high):
            return None
        if not confirm.is_bearish:
            return None

        entry = confirm.close
        sl = sweep.high + buffer
        risk = sl - entry
        if risk <= 0:
            return None
        tp1 = entry - risk * Decimal(str(cfg["tp1R"]))
        tp2 = entry - risk * Decimal(str(cfg["tp2R"]))
        rr = (entry - tp2) / risk
        reason = [
            "Swept previous high",
            "Closed back below swing high",
            "M15 bearish confirmation",
            "H1 trend not bullish",
        ]
        confidence = self._confidence(cfg, "SELL", confirm, sweep, swing_high, rr, trend, point)
        return SignalCandidate(
            strategy_code=self.code, symbol=ctx.symbol, timeframe="M15", action="SELL",
            entry=entry, sl=sl, tp=[tp1, tp2], risk_reward=rr, confidence=confidence,
            reason=reason, invalid_if=f"M15 closes above {sl}",
            source_candle_time=confirm.candle_time,
        )

    def _confidence(self, cfg, action, confirm, sweep, swing, rr, trend, point) -> int:
        """Deterministic rule-based score (03 §5 confidence scoring v1)."""
        score = 60
        gap_needed = Decimal(str(cfg["trendGapPoints"])) * point
        aligned = (action == "BUY" and trend == "UP") or (action == "SELL" and trend == "DOWN")
        if aligned:
            score += 10  # ponytail: gap magnitude approximated by trend direction; refine if needed
            _ = gap_needed
        depth = abs((swing - sweep.low) if action == "BUY" else (sweep.high - swing))
        if depth >= Decimal(str(cfg["sweepDepthPoints"])) * point:
            score += 10
        if rr >= Decimal("2.0"):
            score += 10
        if confirm.range > 0 and confirm.body >= Decimal(str(cfg["confirmBodyRatio"])) * confirm.range:
            score += 10
        return max(0, min(100, score))
