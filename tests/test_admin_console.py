"""Milestone E: Admin Console screens render + write actions audit (12 spec)."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal as D

import pytest
from sqlalchemy import func, select

from app.models import (
    AdminActivityLog,
    DataSourceFeed,
    GroupStrategySetting,
    GroupStrategySymbol,
    GroupStrategyTimeframe,
    Signal,
    TelegramGroup,
    TelegramOutbox,
)
from app.security.session import COOKIE_NAME, read_session

pytestmark = pytest.mark.integration


def _session_csrf(client):
    return read_session(client.cookies.get(COOKIE_NAME))["csrf"]


# --- screens render ---

@pytest.mark.parametrize("path", [
    "/admin", "/admin/feeds", "/admin/groups", "/admin/strategies",
    "/admin/signals", "/admin/deliveries", "/admin/settings",
])
def test_screens_render(logged_in_client, path):
    r = logged_in_client.get(path)
    assert r.status_code == 200
    assert "tradebot" in r.text


def test_feed_matrix_shows_six_feeds(logged_in_client):
    r = logged_in_client.get("/admin")
    # 3 symbols x 2 timeframes = 6 rows in the feed table
    assert r.text.count("XAUUSD") >= 2  # M15 + H1
    for sym in ("XAUUSD", "EURUSD", "GBPUSD"):
        assert sym in r.text


def test_overview_shows_runbook_when_feed_degraded(logged_in_client, db):
    feed = db.scalar(
        select(DataSourceFeed).where(
            DataSourceFeed.canonical_symbol == "XAUUSD",
            DataSourceFeed.timeframe == "M15",
        )
    )
    feed.status = "STALE"
    feed.last_candle_time = datetime.now(timezone.utc) - timedelta(minutes=feed.stale_after_minutes + 10)
    db.flush()

    r = logged_in_client.get("/admin")

    assert r.status_code == 200
    assert "Cách xử lý" in r.text
    assert "Feed TradingView stale/error" in r.text
    assert "Mở Feeds" in r.text
    assert "tạm pause group" in r.text


def test_settings_masks_secret(logged_in_client):
    r = logged_in_client.get("/admin/settings")
    assert "********" in r.text


def test_admin_lists_render_pagination(logged_in_client):
    signals = logged_in_client.get("/admin/signals?page=1&per_page=10")
    deliveries = logged_in_client.get("/admin/deliveries?tab=PENDING&page=1&per_page=10")

    assert signals.status_code == 200
    assert "Trang 1/" in signals.text
    assert deliveries.status_code == 200
    assert "Trang 1/" in deliveries.text


# --- write actions + audit ---

def test_create_group_writes_audit(logged_in_client, db):
    csrf = _session_csrf(logged_in_client)
    before = db.scalar(select(func.count()).select_from(TelegramGroup))
    r = logged_in_client.post(
        "/admin/groups",
        data={"name": "New VIP Group", "type": "VIP", "telegram_chat_id": "-100999", "csrf_token": csrf},
        follow_redirects=False,
    )
    assert r.status_code == 303
    after = db.scalar(select(func.count()).select_from(TelegramGroup))
    assert after == before + 1
    logs = db.scalars(
        select(AdminActivityLog).where(AdminActivityLog.action == "create_group")
    ).all()
    assert any(log.resource_type == "telegram_group" for log in logs)


def test_toggle_group_pause_writes_audit(logged_in_client, db):
    csrf = _session_csrf(logged_in_client)
    gid = db.scalar(select(TelegramGroup.id).order_by(TelegramGroup.id).limit(1))
    logged_in_client.post(
        f"/admin/groups/{gid}/toggle", data={"csrf_token": csrf}, follow_redirects=False
    )
    log = db.scalar(
        select(AdminActivityLog).where(AdminActivityLog.action == "toggle_group_pause")
    )
    assert log is not None and log.resource_id == str(gid)


def test_update_group_strategy_setting_writes_audit(logged_in_client, db):
    csrf = _session_csrf(logged_in_client)
    setting = db.scalar(select(GroupStrategySetting).order_by(GroupStrategySetting.id).limit(1))

    response = logged_in_client.post(
        f"/admin/strategies/settings/{setting.id}",
        data={
            "csrf_token": csrf,
            "min_confidence": "82",
            "send_mode": "BASIC",
            "cooldown_minutes": "45",
            "min_rr": "1.7",
            "is_active": "on",
            "symbols": ["XAUUSD", "EURUSD"],
            "timeframes": ["M15"],
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    db.refresh(setting)
    assert setting.min_confidence == 82
    assert setting.send_mode == "BASIC"
    assert setting.cooldown_minutes == 45
    assert str(setting.min_rr) == "1.7"
    symbols = db.scalars(
        select(GroupStrategySymbol.symbol)
        .where(GroupStrategySymbol.setting_id == setting.id)
        .order_by(GroupStrategySymbol.symbol)
    ).all()
    timeframes = db.scalars(
        select(GroupStrategyTimeframe.timeframe).where(GroupStrategyTimeframe.setting_id == setting.id)
    ).all()
    assert symbols == ["EURUSD", "XAUUSD"]
    assert timeframes == ["M15"]
    log = db.scalar(
        select(AdminActivityLog).where(AdminActivityLog.action == "update_group_strategy_setting")
    )
    assert log is not None and log.resource_id == str(setting.id)


def test_activate_live_blocks_placeholder_group(logged_in_client, db):
    csrf = _session_csrf(logged_in_client)
    group = db.scalar(select(TelegramGroup).order_by(TelegramGroup.id).limit(1))

    r = logged_in_client.post(
        f"/admin/groups/{group.id}/activate-live",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )

    assert r.status_code == 303
    db.refresh(group)
    assert group.mode == "DEMO"
    assert group.is_active is False
    assert "placeholder" in group.notes
    log = db.scalar(
        select(AdminActivityLog).where(AdminActivityLog.action == "activate_live_group_blocked")
    )
    assert log is not None


def test_activate_live_requires_successful_test_message(logged_in_client, db):
    csrf = _session_csrf(logged_in_client)
    group = db.scalar(select(TelegramGroup).order_by(TelegramGroup.id).limit(1))
    group.telegram_chat_id = "-100123"
    group.last_delivery_status = "FAILED_RETRYABLE"
    db.flush()

    logged_in_client.post(
        f"/admin/groups/{group.id}/activate-live",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )

    db.refresh(group)
    assert group.mode == "DEMO"
    assert group.is_active is False
    assert "test message" in group.notes


def test_activate_live_group_after_successful_test(logged_in_client, db):
    csrf = _session_csrf(logged_in_client)
    group = db.scalar(select(TelegramGroup).order_by(TelegramGroup.id).limit(1))
    group.telegram_chat_id = "-100123"
    group.last_delivery_status = "SENT"
    group.last_test_message_at = datetime.now(timezone.utc)
    db.flush()

    r = logged_in_client.post(
        f"/admin/groups/{group.id}/activate-live",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )

    assert r.status_code == 303
    db.refresh(group)
    assert group.mode == "LIVE"
    assert group.is_active is True
    assert group.is_paused is False
    assert group.notes is None
    log = db.scalar(select(AdminActivityLog).where(AdminActivityLog.action == "activate_live_group"))
    assert log is not None


def test_signal_detail_shows_timeline(logged_in_client, db):
    sig = Signal(
        signal_uid="uid-detail-1", source="tradingview_bars", strategy_code="liquidity_sweep",
        symbol="XAUUSD", timeframe="M15", action="BUY", status="APPROVED",
        entry=D("2325"), sl=D("2318"), tp=["2332", "2340"], risk_reward=D("1.8"),
        confidence=90, reason=["Swept previous low"], invalid_if="below 2318",
        source_candle_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    db.add(sig)
    db.flush()
    from app.models import SignalEvent
    db.add(SignalEvent(signal_id=sig.id, event_type="SIGNAL_APPROVED", message="ok"))
    db.flush()

    r = logged_in_client.get(f"/admin/signals/{sig.id}")
    assert r.status_code == 200
    assert "SIGNAL_APPROVED" in r.text
    assert "Event timeline" in r.text


def test_retry_delivery_writes_audit(logged_in_client, db, monkeypatch):
    # create a retryable outbox row
    sig = Signal(
        signal_uid="uid-retry-1", source="x", strategy_code="liquidity_sweep",
        symbol="XAUUSD", timeframe="M15", action="BUY", status="QUEUED",
        entry=D("2325"), sl=D("2318"), tp=["2332", "2340"], risk_reward=D("1.8"),
        confidence=90, invalid_if="below 2318",
        source_candle_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    db.add(sig)
    db.flush()
    gid = db.scalar(select(TelegramGroup.id).order_by(TelegramGroup.id).limit(1))
    ob = TelegramOutbox(
        delivery_uid="uid-retry-1:g", signal_id=sig.id, group_id=gid,
        status="FAILED_RETRYABLE", message_text="hi", attempt_count=1,
    )
    db.add(ob)
    db.flush()

    from app.services import delivery
    from app.telegram.client import SendResult
    monkeypatch.setattr(delivery, "send_message",
                        lambda chat, text: SendResult(True, False, 200, message_id="ok"))

    csrf = _session_csrf(logged_in_client)
    logged_in_client.post(
        f"/admin/deliveries/{ob.id}/retry", data={"csrf_token": csrf}, follow_redirects=False
    )
    log = db.scalar(select(AdminActivityLog).where(AdminActivityLog.action == "retry_delivery"))
    assert log is not None
    db.refresh(ob)
    assert ob.status == "SENT"


def test_csrf_required_for_group_create(logged_in_client, db):
    before = db.scalar(select(func.count()).select_from(TelegramGroup))
    logged_in_client.post(
        "/admin/groups",
        data={"name": "No CSRF", "type": "VIP", "telegram_chat_id": "-1", "csrf_token": "wrong"},
        follow_redirects=False,
    )
    after = db.scalar(select(func.count()).select_from(TelegramGroup))
    assert after == before  # rejected, no group created
