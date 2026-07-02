"""Unit tests for Liquidity Sweep + risk + uid + indicators. Pure, no DB."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal as D

from app.strategy.indicators import ema, session_label
from app.strategy.liquidity_sweep import LiquiditySweepStrategy
from app.strategy.registry import get_strategy
from app.strategy.risk import build_signal_uid, check_risk
from app.strategy.types import Candle, RejectCode, SignalCandidate, StrategyContext

_T0 = datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)


def _c(i, o, h, low, cl):
    return Candle(_T0 + timedelta(minutes=15 * i), D(str(o)), D(str(h)), D(str(low)), D(str(cl)))


def _rising_h1(n=51):
    return [
        Candle(_T0 + timedelta(hours=i), D(str(90 + i * 0.1)), D(str(91 + i * 0.1)),
               D(str(89 + i * 0.1)), D(str(90.5 + i * 0.1)))
        for i in range(n)
    ]


def _falling_h1(n=51):
    return [
        Candle(_T0 + timedelta(hours=i), D(str(200 - i * 0.1)), D(str(201 - i * 0.1)),
               D(str(199 - i * 0.1)), D(str(199.5 - i * 0.1)))
        for i in range(n)
    ]


def _ctx(m15, h1):
    return StrategyContext(
        symbol="XAUUSD", trigger_timeframe="M15", timeframes={"M15": m15, "H1": h1},
        session="LONDON", spread=None, strategy_config={},
        symbol_config={"point_size": "0.01", "sl_buffer_points": "20"},
    )


# --- indicators ---

def test_ema_returns_none_without_enough_data():
    assert ema([D("1"), D("2")], 5) is None


def test_ema_rising_series_positive_slope():
    vals = [D(str(x)) for x in range(1, 30)]
    assert ema(vals, 10) > ema(vals[:20], 10)


def test_session_priority_london_over_newyork():
    assert session_label(datetime(2026, 1, 1, 13, 0, tzinfo=timezone.utc)) == "LONDON"


# --- strategy ---

def test_buy_signal_from_fake_candles():
    m15 = [_c(i, 100, 101, 99, 100) for i in range(20)]
    m15.append(_c(20, 100, 100.5, 94, 99.5))   # sweep below swing low, close back above
    m15.append(_c(21, 99.5, 102, 99.4, 101.5))  # bullish confirm
    out = LiquiditySweepStrategy().detect(_ctx(m15, _rising_h1()))
    assert len(out) == 1
    s = out[0]
    assert s.action == "BUY"
    assert s.sl < s.entry < s.tp[0] < s.tp[1]
    assert s.risk_reward >= D("1.5")
    assert s.confidence >= 60


def test_sell_signal_from_fake_candles():
    m15 = [_c(i, 100, 101, 99, 100) for i in range(20)]
    m15.append(_c(20, 100, 106, 99.5, 100.5))   # sweep above swing high, close back below
    m15.append(_c(21, 100.5, 100.6, 98, 98.5))  # bearish confirm
    out = LiquiditySweepStrategy().detect(_ctx(m15, _falling_h1()))
    assert len(out) == 1
    s = out[0]
    assert s.action == "SELL"
    assert s.tp[1] < s.tp[0] < s.entry < s.sl


def test_no_setup_returns_empty():
    m15 = [_c(i, 100, 101, 99, 100) for i in range(22)]  # flat, no sweep
    assert LiquiditySweepStrategy().detect(_ctx(m15, _rising_h1())) == []


def test_lookback_values():
    s = get_strategy("liquidity_sweep")
    assert s.lookback("M15") == 22
    assert s.lookback("H1") == 51


# --- risk ---

def _candidate(action="BUY", entry="100", sl="98", tp2="104"):
    return SignalCandidate(
        strategy_code="liquidity_sweep", symbol="XAUUSD", timeframe="M15", action=action,
        entry=D(entry), sl=D(sl), tp=[D("102"), D(tp2)], risk_reward=D("2"),
        confidence=70, reason=["x"], invalid_if="below 98", source_candle_time=_T0,
    )


def test_risk_passes_good_buy():
    assert check_risk(_candidate(), min_rr=D("1.5"), spread=None, max_spread=None) is None


def test_risk_rejects_low_rr():
    c = _candidate(tp2="101")  # reward 1 vs risk 2 -> rr 0.5
    assert check_risk(c, min_rr=D("1.5"), spread=None, max_spread=None) == RejectCode.RR_TOO_LOW


def test_risk_skips_spread_when_null():
    assert check_risk(_candidate(), min_rr=D("1.5"), spread=None, max_spread=D("5")) is None


def test_risk_rejects_high_spread_when_present():
    assert check_risk(_candidate(), min_rr=D("1.5"), spread=D("50"), max_spread=D("30")) == RejectCode.SPREAD_TOO_HIGH


def test_risk_rejects_invalid_math():
    c = _candidate(entry="100", sl="100")  # risk 0
    assert check_risk(c, min_rr=D("1.5"), spread=None, max_spread=None) == RejectCode.INVALID_RR_MATH


# --- uid ---

def test_signal_uid_deterministic_and_bucketed():
    c = _candidate(entry="2325.50")
    uid = build_signal_uid(c, point_size=D("0.01"), entry_tolerance_points=D("20"))
    uid2 = build_signal_uid(c, point_size=D("0.01"), entry_tolerance_points=D("20"))
    assert uid == uid2
    assert uid.startswith("liquidity_sweep:XAUUSD:M15:BUY:2026-01-01T08:00:00Z:")
