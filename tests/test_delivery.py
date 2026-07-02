"""Integration: router eligibility/outbox + delivery worker retry/aggregate (05 specs)."""

from datetime import datetime, timezone
from decimal import Decimal as D

import pytest
from sqlalchemy import func, select

from app.models import (
    GroupStrategySetting,
    Signal,
    SignalDelivery,
    TelegramGroup,
    TelegramOutbox,
)
from app.seed import seed
from app.services import delivery, router
from app.telegram.client import SendResult

pytestmark = pytest.mark.integration

_T0 = datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)


def _approved_signal(db):
    seed(db)
    db.flush()
    sig = Signal(
        signal_uid="liquidity_sweep:XAUUSD:M15:BUY:2026-01-01T08:00:00Z:100",
        source="tradingview_bars", strategy_code="liquidity_sweep", symbol="XAUUSD",
        timeframe="M15", action="BUY", entry=D("2325.5"), sl=D("2318"),
        tp=["2332", "2340"], risk_reward=D("1.8"), confidence=90,
        reason=["Swept previous low"], invalid_if="below 2318",
        source_candle_time=_T0, status="APPROVED",
    )
    db.add(sig)
    db.flush()
    return sig


def _activate_all_groups(db):
    for g in db.scalars(select(TelegramGroup)).all():
        g.is_active = True
        g.telegram_chat_id = f"-100{g.id}"
    db.flush()


def test_eligible_groups_get_outbox(db):
    sig = _approved_signal(db)
    _activate_all_groups(db)
    created = router.route_signal(db, sig)
    db.flush()
    # free_demo min_confidence 75, vip 70, smc 80; confidence 90 passes all 3
    assert len(created) == 3
    assert sig.status == "QUEUED"


def test_inactive_group_gets_no_outbox(db):
    sig = _approved_signal(db)
    # leave all groups inactive (seed default is_active=False)
    for g in db.scalars(select(TelegramGroup)).all():
        g.telegram_chat_id = f"-100{g.id}"
    db.flush()
    created = router.route_signal(db, sig)
    db.flush()
    assert created == []
    assert sig.status == "APPROVED"  # unchanged when nobody eligible


def test_below_min_confidence_skipped(db):
    sig = _approved_signal(db)
    sig.confidence = 78  # below smc_demo (80), passes free(75)+vip(70)
    _activate_all_groups(db)
    created = router.route_signal(db, sig)
    db.flush()
    assert len(created) == 2


def test_duplicate_delivery_uid_blocked(db):
    sig = _approved_signal(db)
    _activate_all_groups(db)
    router.route_signal(db, sig)
    db.flush()
    n1 = db.scalar(select(func.count()).select_from(TelegramOutbox))
    router.route_signal(db, sig)  # same signal again
    db.flush()
    n2 = db.scalar(select(func.count()).select_from(TelegramOutbox))
    assert n1 == n2 == 3


def _one_outbox(db, sig):
    _activate_all_groups(db)
    # narrow to a single group (first one) for delivery tests
    settings = db.scalars(select(GroupStrategySetting).order_by(GroupStrategySetting.id)).all()
    keep = settings[0].group_id
    for s in settings:
        if s.group_id != keep:
            s.is_active = False
    db.flush()
    created = router.route_signal(db, sig)
    db.flush()
    return created[0]


def test_delivery_success_marks_sent(db, monkeypatch):
    sig = _approved_signal(db)
    ob = _one_outbox(db, sig)
    monkeypatch.setattr(
        delivery, "send_message",
        lambda chat, text: SendResult(True, False, 200, message_id="555"),
    )
    delivery.process_outbox_row(db, ob)
    db.flush()
    assert ob.status == "SENT"
    assert ob.telegram_message_id == "555"
    attempts = db.scalars(select(SignalDelivery).where(SignalDelivery.outbox_id == ob.id)).all()
    assert len(attempts) == 1 and attempts[0].status == "SENT"
    db.refresh(sig)
    assert sig.status == "SENT"


def test_retryable_failure_schedules_retry(db, monkeypatch):
    sig = _approved_signal(db)
    ob = _one_outbox(db, sig)
    monkeypatch.setattr(
        delivery, "send_message",
        lambda chat, text: SendResult(False, False, 500, error_code="HTTP_ERROR"),
    )
    delivery.process_outbox_row(db, ob)
    db.flush()
    assert ob.status == "FAILED_RETRYABLE"
    assert ob.attempt_count == 1
    assert ob.next_attempt_at > datetime.now(timezone.utc)


def test_permanent_failure_marks_failed(db, monkeypatch):
    sig = _approved_signal(db)
    ob = _one_outbox(db, sig)
    monkeypatch.setattr(
        delivery, "send_message",
        lambda chat, text: SendResult(False, True, 403, error_code="PERMANENT"),
    )
    delivery.process_outbox_row(db, ob)
    db.flush()
    assert ob.status == "FAILED_PERMANENT"
    db.refresh(sig)
    assert sig.status == "FAILED"


def test_sent_row_reclaim_does_not_resend(db, monkeypatch):
    sig = _approved_signal(db)
    ob = _one_outbox(db, sig)
    ob.telegram_message_id = "already-sent"
    db.flush()
    calls = []
    monkeypatch.setattr(delivery, "send_message", lambda *a: calls.append(1))
    delivery.process_outbox_row(db, ob)
    db.flush()
    assert ob.status == "SENT"
    assert calls == []  # never called Telegram again


def test_max_attempts_becomes_permanent(db, monkeypatch):
    sig = _approved_signal(db)
    ob = _one_outbox(db, sig)
    ob.attempt_count = 2  # next attempt is the 3rd (== max_attempts)
    db.flush()
    monkeypatch.setattr(
        delivery, "send_message",
        lambda chat, text: SendResult(False, False, 500, error_code="HTTP_ERROR"),
    )
    delivery.process_outbox_row(db, ob)
    db.flush()
    assert ob.status == "FAILED_PERMANENT"
