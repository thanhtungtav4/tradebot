"""End-to-end MVP pipeline with fake TradingView bars and mocked Telegram."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models import (
    GroupStrategySetting,
    Signal,
    SignalDelivery,
    TelegramGroup,
    TelegramOutbox,
)
from app.telegram.client import SendResult
from tests.conftest import TEST_BODY_SECRET, TEST_WEBHOOK_TOKEN

pytestmark = pytest.mark.integration

WEBHOOK = f"/api/v1/webhooks/tradingview/bars/{TEST_WEBHOOK_TOKEN}"
T0 = datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)


def _bar(tf: str, time: datetime, o, h, low, cl) -> dict:
    return {
        "secret": TEST_BODY_SECRET,
        "symbol": "OANDA:XAUUSD",
        "timeframe": tf,
        "time": time.isoformat().replace("+00:00", "Z"),
        "open": str(o),
        "high": str(h),
        "low": str(low),
        "close": str(cl),
        "volume": "100",
        "isClosed": True,
    }


class _SessionContext:
    def __init__(self, db):
        self.db = db

    def __enter__(self):
        return self.db

    def __exit__(self, exc_type, exc, tb):
        return False


class _InlineQueue:
    def __init__(self, workers, calls):
        self.workers = workers
        self.calls = calls

    def enqueue(self, func: str, payload: dict):
        self.calls.append((func, payload))
        if func == "app.workers.route_signal":
            self.workers.route_signal(payload)
        elif func == "app.workers.send_telegram":
            self.workers.send_telegram(payload)


def test_fake_webhook_to_signal_outbox_and_mocked_telegram(client, db, monkeypatch):
    queued_strategy_jobs = []

    def fake_enqueue_strategy(symbol, timeframe, candle_time, source_id):
        if timeframe == "M15":
            queued_strategy_jobs.append({
                "symbol": symbol,
                "timeframe": timeframe,
                "candle_time": candle_time.isoformat(),
                "source_id": source_id,
            })
            return True
        return False

    monkeypatch.setattr("app.api.webhooks.enqueue_run_strategy", fake_enqueue_strategy)

    # One live-ish group is enough for the integration path; keep other settings inactive.
    group = db.scalar(select(TelegramGroup).order_by(TelegramGroup.id).limit(1))
    group.telegram_chat_id = "-100999"
    group.is_active = True
    group.is_paused = False
    group.mode = "DEMO"
    settings = db.scalars(select(GroupStrategySetting).order_by(GroupStrategySetting.id)).all()
    for setting in settings:
        setting.is_active = setting.group_id == group.id
        if setting.group_id == group.id:
            setting.min_confidence = 70
    db.flush()

    h1_base = T0 - timedelta(hours=60)
    for i in range(51):
        v = 90 + i * 0.1
        response = client.post(WEBHOOK, json=_bar("H1", h1_base + timedelta(hours=i), v, v + 1, v - 1, v + 0.5))
        assert response.status_code == 200, response.text
        assert response.json()["enqueued"] is False

    for i in range(20):
        response = client.post(WEBHOOK, json=_bar("M15", T0 + timedelta(minutes=15 * i), 100, 101, 99, 100))
        assert response.status_code == 200, response.text
    client.post(WEBHOOK, json=_bar("M15", T0 + timedelta(minutes=15 * 20), 100, 100.5, 94, 99.5))
    client.post(WEBHOOK, json=_bar("M15", T0 + timedelta(minutes=15 * 21), 99.5, 102, 99.4, 101.5))

    assert queued_strategy_jobs

    from app.services import delivery
    from app import workers

    inline_calls = []
    monkeypatch.setattr(workers, "SessionLocal", lambda: _SessionContext(db))
    monkeypatch.setattr(workers, "_queue", lambda name: _InlineQueue(workers, inline_calls))
    monkeypatch.setattr(
        delivery,
        "send_message",
        lambda chat, text: SendResult(True, False, 200, message_id="tg-1"),
    )

    workers.run_strategy(queued_strategy_jobs[-1])
    db.flush()

    signal = db.scalar(select(Signal).where(Signal.status == "SENT"))
    assert signal is not None
    assert signal.action == "BUY"
    outbox = db.scalar(select(TelegramOutbox).where(TelegramOutbox.signal_id == signal.id))
    assert outbox is not None
    assert outbox.status == "SENT"
    assert outbox.telegram_message_id == "tg-1"
    attempt = db.scalar(select(SignalDelivery).where(SignalDelivery.outbox_id == outbox.id))
    assert attempt is not None
    assert attempt.status == "SENT"
    assert ("app.workers.route_signal", {"signal_id": signal.id}) in inline_calls
    assert any(func == "app.workers.send_telegram" for func, _payload in inline_calls)
