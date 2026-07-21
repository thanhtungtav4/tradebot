"""Demo mode: config round-trip + emit routes to an active group."""

from datetime import datetime, timezone

from sqlalchemy import select, update

from app.models import (
    GroupStrategySetting,
    TelegramGroup,
    TelegramOutbox,
)
from app.seed import seed
from app.services import demo, router


def _activate_first_group(db):
    """Seed groups are inactive by default; turn one on so the router matches."""
    setting = db.scalars(select(GroupStrategySetting)).first()
    db.execute(update(GroupStrategySetting).values(is_active=True))
    db.execute(update(TelegramGroup).values(is_active=True, is_paused=False))
    db.flush()
    return setting


def test_config_defaults_and_roundtrip(db):
    seed(db)
    db.flush()

    cfg = demo.get_config(db)
    assert cfg["enabled"] is False
    assert cfg["interval_minutes"] == 15

    demo.set_config(db, enabled=True, interval_minutes=5)
    db.flush()
    cfg = demo.get_config(db)
    assert cfg["enabled"] is True
    assert cfg["interval_minutes"] == 5

    demo.set_config(db, enabled=True, interval_minutes=0)  # clamped to >=1
    db.flush()
    assert demo.get_config(db)["interval_minutes"] == 1


def test_emit_creates_approved_demo_signal_and_routes(db):
    seed(db)
    setting = _activate_first_group(db)

    sig = demo.emit_demo_signal(db)
    assert sig is not None
    assert sig.status == "APPROVED"
    assert sig.metadata_["demo"] is True
    assert sig.confidence >= setting.min_confidence

    outboxes = router.route_signal(db, sig)
    db.flush()
    assert len(outboxes) >= 1
    row = db.get(TelegramOutbox, outboxes[0].id)
    assert row.status == "PENDING"
    assert "demo" in row.message_text.lower()


def test_emit_returns_none_without_active_group(db):
    seed(db)
    db.flush()  # groups inactive
    assert demo.emit_demo_signal(db) is None


def test_mark_run_stamps_timestamp(db):
    seed(db)
    db.flush()
    now = datetime.now(timezone.utc)
    demo.mark_run(db, now)
    db.flush()
    assert demo.get_config(db)["last_run_at"] == now.isoformat()
