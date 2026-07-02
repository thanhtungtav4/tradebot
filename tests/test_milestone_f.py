"""Milestone F: health, stale feed scheduler, outbox retry scheduler, smoke readiness."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal as D

import pytest
from sqlalchemy import select

from app.models import (
    ComponentHealth,
    DataSource,
    DataSourceFeed,
    Signal,
    TelegramGroup,
    TelegramOutbox,
)
from app.seed import seed
from app.services import scheduler

pytestmark = pytest.mark.integration


def test_stale_feed_scan_degrades_component_health(db):
    seed(db)
    db.flush()
    feed = db.scalar(
        select(DataSourceFeed).where(
            DataSourceFeed.canonical_symbol == "XAUUSD",
            DataSourceFeed.timeframe == "M15",
        )
    )
    feed.status = "OK"
    feed.last_candle_time = datetime.now(timezone.utc) - timedelta(minutes=feed.stale_after_minutes + 5)
    db.flush()

    changed = scheduler.scan_stale_feeds(db)
    db.flush()

    assert changed >= 1
    assert feed.status == "STALE"
    health = db.get(ComponentHealth, "data_feed")
    assert health.status == "DEGRADED"
    assert "XAUUSD M15" in health.details["affectedFeeds"]


def test_stale_feed_scan_preserves_fresh_warmup(db):
    seed(db)
    db.flush()
    feed = db.scalar(
        select(DataSourceFeed).where(
            DataSourceFeed.canonical_symbol == "EURUSD",
            DataSourceFeed.timeframe == "M15",
        )
    )
    feed.status = "WARMUP"
    feed.last_candle_time = datetime.now(timezone.utc)
    db.flush()

    scheduler.scan_stale_feeds(db)
    db.flush()

    assert feed.status == "WARMUP"


def _queued_outbox(db, *, status="PENDING", locked=False):
    seed(db)
    db.flush()
    sig = Signal(
        signal_uid=f"milestone-f-{status}-{locked}",
        source="x",
        strategy_code="liquidity_sweep",
        symbol="XAUUSD",
        timeframe="M15",
        action="BUY",
        status="QUEUED",
        entry=D("2325"),
        sl=D("2318"),
        tp=["2332", "2340"],
        risk_reward=D("1.8"),
        confidence=90,
        invalid_if="below 2318",
        source_candle_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    db.add(sig)
    db.flush()
    gid = db.scalar(select(TelegramGroup.id).order_by(TelegramGroup.id).limit(1))
    ob = TelegramOutbox(
        delivery_uid=f"{sig.signal_uid}:g",
        signal_id=sig.id,
        group_id=gid,
        status=status,
        message_text="hi",
        next_attempt_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    if locked:
        ob.locked_until = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.add(ob)
    db.flush()
    return ob


def test_outbox_retry_scan_enqueues_due_and_stale_sending(db):
    due = _queued_outbox(db, status="FAILED_RETRYABLE")
    stale = _queued_outbox(db, status="SENDING", locked=True)
    sent = _queued_outbox(db, status="SENT")
    db.flush()

    enqueued = []
    count = scheduler.scan_outbox_retry(db, enqueued.append)

    assert count >= 2
    assert due.id in enqueued
    assert stale.id in enqueued
    assert sent.id not in enqueued


def test_health_endpoint_uses_component_contract(client, monkeypatch):
    def fake_collect(db, persist=True):
        return "OK", {
            "api": {"status": "OK"},
            "db": {"status": "OK"},
            "redis": {"status": "OK"},
            "data_feed": {"status": "OK"},
            "market_worker": {"status": "OK"},
            "signal_worker": {"status": "OK"},
            "telegram_worker": {"status": "OK"},
            "scheduler": {"status": "OK"},
            "telegram_api": {"status": "OK"},
        }

    monkeypatch.setattr("app.api.health.collect_health", fake_collect)
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "OK"
    assert body["components"]["telegram_worker"]["status"] == "OK"


def _import_bar(**over):
    base = {
        "symbol": "OANDA:XAUUSD",
        "timeframe": "M15",
        "time": "2026-01-02T00:00:00Z",
        "open": "2000.0",
        "high": "2010.0",
        "low": "1995.0",
        "close": "2005.0",
        "volume": "100",
        "isClosed": True,
    }
    base.update(over)
    return base


def test_candle_import_requires_bearer(client):
    response = client.post("/api/v1/admin/candles/import", json={"candles": [_import_bar()]})
    assert response.status_code == 401


def test_candle_import_reuses_ingest_path(client, db, monkeypatch):
    enqueued = []

    def fake_enqueue(symbol, timeframe, candle_time, source_id):
        if timeframe == "M15":
            enqueued.append(timeframe)
            return True
        return False

    monkeypatch.setattr(
        "app.api.admin.enqueue_run_strategy",
        fake_enqueue,
    )
    response = client.post(
        "/api/v1/admin/candles/import",
        headers={"Authorization": "Bearer test-admin-api-key-abcdefghijklmnop"},
        json={"candles": [_import_bar(), _import_bar(timeframe="H1", time="2026-01-02T01:00:00Z")]},
    )

    assert response.status_code == 200, response.text
    assert response.json()["imported"] == 2
    assert enqueued == ["M15"]
    feed = db.scalar(
        select(DataSourceFeed).where(
            DataSourceFeed.canonical_symbol == "XAUUSD",
            DataSourceFeed.timeframe == "H1",
        )
    )
    assert feed.last_candle_time is not None


def _mark_release_ready(db):
    seed(db)
    db.flush()
    now = datetime.now(timezone.utc)
    for health in db.scalars(select(ComponentHealth)).all():
        health.status = "OK"
        health.summary = "ok"
        health.checked_at = now
        health.last_ok_at = now
    for feed in db.scalars(select(DataSourceFeed)).all():
        feed.status = "OK"
        feed.last_candle_time = now
        feed.last_payload_received_at = now
    for source in db.scalars(select(DataSource)).all():
        source.status = "OK"
        source.last_ok_at = now
        source.last_payload_received_at = now
    db.flush()


def test_release_check_passes_ready_database(client, db):
    from app.config.settings import get_settings
    from scripts.release_check import run_checks

    _mark_release_ready(db)

    results = run_checks(db, get_settings())

    assert all(result.ok for result in results), [r for r in results if not r.ok]


def test_release_check_blocks_active_placeholder_group(client, db):
    from app.config.settings import get_settings
    from scripts.release_check import run_checks

    _mark_release_ready(db)
    group = db.scalar(select(TelegramGroup).where(TelegramGroup.telegram_chat_id.like("PLACEHOLDER%")))
    group.is_active = True
    db.flush()

    results = run_checks(db, get_settings())

    failed = {result.code for result in results if not result.ok}
    assert "no_live_placeholder_groups" in failed
