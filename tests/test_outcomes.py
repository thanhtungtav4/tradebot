"""Integration tests for backtesting and outcome tracking (Phase E)."""

import pytest
from datetime import datetime, timezone, timedelta
from sqlalchemy import select
from app.models import Signal, MarketCandle, SignalEvent, DataSource
from app.services.scheduler import scan_signal_outcomes

pytestmark = pytest.mark.integration


def test_manual_outcome_update(client, db):
    # Setup test signal
    sig = Signal(
        signal_uid="outcome-manual-test",
        source="tradingview_bars",
        strategy_code="liquidity_sweep",
        symbol="XAUUSD",
        timeframe="M15",
        action="BUY",
        entry=2000.0,
        sl=1990.0,
        tp=["2015.0"],
        risk_reward=1.5,
        confidence=80,
        invalid_if="Price breaks low",
        status="APPROVED"
    )
    db.add(sig)
    db.commit()

    # Call API to update outcome
    url = f"/api/v1/admin/signals/{sig.id}/outcome"
    headers = {"Authorization": "Bearer test-admin-api-key-abcdefghijklmnop"}
    payload = {"status": "WIN", "reason": "TP hit manually"}
    
    resp = client.post(url, json=payload, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["outcome"]["status"] == "WIN"

    # Reload signal and verify metadata/event
    db.refresh(sig)
    assert sig.metadata_["outcome"]["status"] == "WIN"
    assert sig.metadata_["outcome"]["reason"] == "TP hit manually"

    event = db.scalar(
        select(SignalEvent).where(
            SignalEvent.signal_id == sig.id,
            SignalEvent.event_type == "SIGNAL_STATUS_UPDATED"
        )
    )
    assert event is not None
    assert "WIN" in event.message


def test_auto_outcome_scan_win(client, db):
    # Fetch seeded source
    source = db.scalar(select(DataSource).where(DataSource.code == "tradingview_bars"))
    assert source is not None

    # Setup approved BUY signal
    sig_time = datetime.now(timezone.utc) - timedelta(hours=2)
    sig = Signal(
        signal_uid="outcome-auto-win-test",
        source="tradingview_bars",
        strategy_code="liquidity_sweep",
        symbol="XAUUSD",
        timeframe="M15",
        action="BUY",
        entry=2000.0,
        sl=1990.0,
        tp=["2015.0"],
        risk_reward=1.5,
        confidence=80,
        invalid_if="Price breaks low",
        status="APPROVED",
        source_candle_time=sig_time
    )
    db.add(sig)
    db.commit()

    # Add closed candle hitting TP
    candle = MarketCandle(
        source_id=source.id,
        source_code="tradingview_bars",
        symbol="XAUUSD",
        source_symbol="OANDA:XAUUSD",
        timeframe="M15",
        candle_time=sig_time + timedelta(minutes=15),
        open=2000.0,
        high=2016.0,  # hits TP (2015.0)
        low=1995.0,   # does not hit SL (1990.0)
        close=2005.0,
        is_closed=True
    )
    db.add(candle)
    db.commit()

    # Run auto outcome scanner
    scanned = scan_signal_outcomes(db)
    assert scanned == 1
    db.flush()

    db.refresh(sig)
    assert sig.metadata_["outcome"]["status"] == "WIN"
    assert "Take Profit 1 hit" in sig.metadata_["outcome"]["reason"]


def test_auto_outcome_scan_loss(client, db):
    # Fetch seeded source
    source = db.scalar(select(DataSource).where(DataSource.code == "tradingview_bars"))
    assert source is not None

    # Setup approved BUY signal
    sig_time = datetime.now(timezone.utc) - timedelta(hours=2)
    sig = Signal(
        signal_uid="outcome-auto-loss-test",
        source="tradingview_bars",
        strategy_code="liquidity_sweep",
        symbol="XAUUSD",
        timeframe="M15",
        action="BUY",
        entry=2000.0,
        sl=1990.0,
        tp=["2015.0"],
        risk_reward=1.5,
        confidence=80,
        invalid_if="Price breaks low",
        status="APPROVED",
        source_candle_time=sig_time
    )
    db.add(sig)
    db.commit()

    # Add closed candle hitting SL
    candle = MarketCandle(
        source_id=source.id,
        source_code="tradingview_bars",
        symbol="XAUUSD",
        source_symbol="OANDA:XAUUSD",
        timeframe="M15",
        candle_time=sig_time + timedelta(minutes=15),
        open=2000.0,
        high=2002.0,  # does not hit TP (2015.0)
        low=1988.0,   # hits SL (1990.0)
        close=1991.0,
        is_closed=True
    )
    db.add(candle)
    db.commit()

    # Run auto outcome scanner
    scanned = scan_signal_outcomes(db)
    assert scanned == 1
    db.flush()

    db.refresh(sig)
    assert sig.metadata_["outcome"]["status"] == "LOSS"
    assert "Stop Loss hit" in sig.metadata_["outcome"]["reason"]
