"""Demo mode: emit synthetic APPROVED signals through the real pipeline.

Toggled from the admin UI. When enabled, a periodic worker generates a fake
signal that is routed and delivered exactly like a real one, so groups can see
end-to-end message delivery without waiting for a live TradingView setup.
"""

import logging
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AppSetting,
    GroupStrategySetting,
    GroupStrategySymbol,
    GroupStrategyTimeframe,
    Signal,
    Strategy,
    SignalEvent,
    TelegramGroup,
)

logger = logging.getLogger("demo")

_SETTING_KEY = "demo_mode"
_DEFAULT = {"enabled": False, "interval_minutes": 15, "last_run_at": None}


def get_config(db: Session) -> dict:
    row = db.get(AppSetting, _SETTING_KEY)
    return {**_DEFAULT, **(row.value if row else {})}


def _write(db: Session, patch: dict) -> dict:
    row = db.get(AppSetting, _SETTING_KEY)
    value = {**_DEFAULT, **(row.value if row else {}), **patch}
    if row is None:
        db.add(AppSetting(key=_SETTING_KEY, value=value))
    else:
        row.value = value
    return value


def set_config(db: Session, *, enabled: bool, interval_minutes: int) -> dict:
    return _write(db, {"enabled": enabled, "interval_minutes": max(1, interval_minutes)})


def mark_run(db: Session, when: datetime) -> None:
    _write(db, {"last_run_at": when.isoformat()})


def _pick_target(db: Session) -> tuple[GroupStrategySetting, str, str, Strategy] | None:
    """First active group setting with at least one symbol+timeframe, so the
    router will actually match the demo signal to a real group."""
    settings = db.scalars(
        select(GroupStrategySetting).where(GroupStrategySetting.is_active.is_(True))
    ).all()
    for s in settings:
        group = db.get(TelegramGroup, s.group_id)
        if group is None or not group.is_active or group.is_paused:
            continue
        strat = db.get(Strategy, s.strategy_id)
        if strat is None:
            continue
        symbol = db.scalar(
            select(GroupStrategySymbol.symbol).where(GroupStrategySymbol.setting_id == s.id)
        )
        tf = db.scalar(
            select(GroupStrategyTimeframe.timeframe).where(GroupStrategyTimeframe.setting_id == s.id)
        )
        if symbol and tf:
            return s, symbol, tf, strat
    return None


def emit_demo_signal(db: Session) -> Signal | None:
    """Insert one APPROVED demo signal. Returns it, or None if no eligible group."""
    target = _pick_target(db)
    if target is None:
        logger.info("demo_no_target")
        return None
    setting, symbol, tf, strat = target

    now = datetime.now(timezone.utc)
    uid = f"demo:{symbol}:{tf}:{now.strftime('%Y-%m-%dT%H:%M:%SZ')}"
    entry = Decimal("100.00")
    sig = Signal(
        signal_uid=uid, source="demo", source_id=None,
        strategy_code=strat.code, symbol=symbol, timeframe=tf, action="BUY",
        entry=entry, sl=entry - 2, tp=[str(entry + 3), str(entry + 6)],
        risk_reward=Decimal("1.5"),
        confidence=max(int(setting.min_confidence), 90),
        reason=["Demo signal", "Kiểm tra gửi Telegram"],
        invalid_if="Chỉ là tín hiệu demo, không giao dịch",
        source_candle_time=now, status="APPROVED",
        metadata_={"demo": True, "telegram_reason": "Đây là tín hiệu DEMO để kiểm tra hệ thống."},
    )
    db.add(sig)
    db.flush()
    db.add(SignalEvent(signal_id=sig.id, event_type="SIGNAL_APPROVED",
                       message="Demo signal created", details={"demo": True}))
    logger.info("demo_signal_emitted", extra={"extra_fields": {"signalId": sig.id, "uid": uid}})
    return sig
