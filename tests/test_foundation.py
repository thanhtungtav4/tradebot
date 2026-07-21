"""Milestone A acceptance: migration smoke, seed repeat-safe, key DB constraints."""

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from app.models import DataSourceFeed, MarketCandle, Signal, TelegramOutbox
from app.seed import seed

pytestmark = pytest.mark.integration

EXPECTED_TABLES = 17


def test_migration_creates_all_tables(migrated_db):
    with migrated_db.connect() as conn:
        n = conn.execute(
            text(
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_schema='public' AND table_name NOT LIKE 'alembic%'"
            )
        ).scalar()
    assert n == EXPECTED_TABLES


def test_seed_is_repeat_safe(db):
    seed(db)
    db.flush()
    first = db.scalar(select(func.count()).select_from(DataSourceFeed))
    seed(db)
    db.flush()
    second = db.scalar(select(func.count()).select_from(DataSourceFeed))
    assert first == second == 6


def test_seed_materializes_stale_thresholds(db):
    seed(db)
    db.flush()
    rows = db.execute(
        select(DataSourceFeed.timeframe, DataSourceFeed.stale_after_minutes)
    ).all()
    by_tf = {tf: mins for tf, mins in rows}
    assert by_tf["M15"] == 35
    assert by_tf["H1"] == 80


def test_candle_unique_key_blocks_duplicate(db):
    seed(db)
    db.flush()
    src_id = db.scalar(text("SELECT id FROM data_sources LIMIT 1"))
    kw = dict(
        source_id=src_id,
        source_code="tradingview_bars",
        symbol="XAUUSD",
        source_symbol="OANDA:XAUUSD",
        timeframe="M15",
        candle_time="2026-01-01T00:00:00Z",
        open=1, high=2, low=0.5, close=1.5,
    )
    db.add(MarketCandle(**kw))
    db.flush()
    db.add(MarketCandle(**kw))
    with pytest.raises(IntegrityError):
        db.flush()


def test_candle_high_low_check(db):
    seed(db)
    db.flush()
    src_id = db.scalar(text("SELECT id FROM data_sources LIMIT 1"))
    db.add(
        MarketCandle(
            source_id=src_id, source_code="x", symbol="XAUUSD",
            source_symbol="OANDA:XAUUSD", timeframe="M15",
            candle_time="2026-01-01T00:15:00Z",
            open=1, high=0.5, low=2, close=1.5,  # high < low: violates CHECK
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()


def test_signal_uid_blocks_duplicate(db):
    seed(db)
    db.flush()
    kw = dict(
        signal_uid="liquidity_sweep:XAUUSD:M15:BUY:2026-01-01T00:00:00Z:1",
        source="tradingview_bars", strategy_code="liquidity_sweep",
        symbol="XAUUSD", timeframe="M15", action="BUY",
    )
    db.add(Signal(**kw))
    db.flush()
    db.add(Signal(**kw))
    with pytest.raises(IntegrityError):
        db.flush()


def test_outbox_delivery_uid_blocks_duplicate(db):
    seed(db)
    db.flush()
    sig = Signal(
        signal_uid="s1", source="x", strategy_code="liquidity_sweep",
        symbol="XAUUSD", timeframe="M15", action="BUY",
    )
    db.add(sig)
    db.flush()
    gid = db.scalar(text("SELECT id FROM telegram_groups LIMIT 1"))
    kw = dict(delivery_uid="s1:1", signal_id=sig.id, group_id=gid, message_text="hi")
    db.add(TelegramOutbox(**kw))
    db.flush()
    db.add(TelegramOutbox(delivery_uid="s1:1", signal_id=sig.id, group_id=gid, message_text="hi2"))
    with pytest.raises(IntegrityError):
        db.flush()
