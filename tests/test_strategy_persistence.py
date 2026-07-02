"""Integration: strategy_runner persists signals + events (warmup, approved, duplicate)."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal as D

import pytest
from sqlalchemy import func, select

from app.models import MarketCandle, Signal, SignalEvent
from app.seed import seed
from app.services.strategy_runner import run_strategy

pytestmark = pytest.mark.integration

_T0 = datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)


def _seed_source(db):
    seed(db)
    db.flush()
    from app.models import DataSource
    return db.scalar(select(DataSource.id).limit(1))


def _add_candle(db, source_id, tf, i, o, h, low, cl, base):
    db.add(MarketCandle(
        source_id=source_id, source_code="tradingview_bars", symbol="XAUUSD",
        source_symbol="OANDA:XAUUSD", timeframe=tf,
        candle_time=base + timedelta(minutes=(15 if tf == "M15" else 60) * i),
        open=D(str(o)), high=D(str(h)), low=D(str(low)), close=D(str(cl)),
    ))


def test_warmup_creates_reject_row_and_event(db):
    src = _seed_source(db)
    # only 2 M15 candles, no H1 -> INSUFFICIENT_HISTORY
    for i in range(2):
        _add_candle(db, src, "M15", i, 100, 101, 99, 100, _T0)
    db.flush()

    sig = run_strategy(db, symbol="XAUUSD", timeframe="M15", source_id=src)
    db.flush()
    assert sig.status == "REJECTED"
    assert sig.reject_code == "INSUFFICIENT_HISTORY"
    events = db.scalars(select(SignalEvent).where(SignalEvent.signal_id == sig.id)).all()
    assert any(e.event_type == "WARMUP_SKIPPED" for e in events)


def test_approved_signal_and_duplicate_guard(db):
    src = _seed_source(db)
    # 22 M15: flat then sweep-low + bullish confirm
    for i in range(20):
        _add_candle(db, src, "M15", i, 100, 101, 99, 100, _T0)
    _add_candle(db, src, "M15", 20, 100, 100.5, 94, 99.5, _T0)
    _add_candle(db, src, "M15", 21, 99.5, 102, 99.4, 101.5, _T0)
    # 51 rising H1
    h1_base = _T0 - timedelta(hours=60)
    for i in range(51):
        v = 90 + i * 0.1
        _add_candle(db, src, "H1", i, v, v + 1, v - 1, v + 0.5, h1_base)
    db.flush()

    sig = run_strategy(db, symbol="XAUUSD", timeframe="M15", source_id=src)
    db.flush()
    assert sig.status == "APPROVED"
    assert sig.action == "BUY"
    events = db.scalars(select(SignalEvent).where(SignalEvent.signal_id == sig.id)).all()
    assert any(e.event_type == "SIGNAL_APPROVED" for e in events)

    before = db.scalar(select(func.count()).select_from(Signal))
    # second run, same candles -> same uid -> duplicate, no new signal
    run_strategy(db, symbol="XAUUSD", timeframe="M15", source_id=src)
    db.flush()
    after = db.scalar(select(func.count()).select_from(Signal))
    assert after == before
