"""Router + group eligibility: approved signal -> telegram_outbox rows (05 §3-§4)."""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    GroupStrategySetting,
    GroupStrategySymbol,
    GroupStrategyTimeframe,
    Signal,
    SignalEvent,
    Strategy,
    TelegramGroup,
    TelegramOutbox,
)
from app.telegram.formatter import DEFAULT_SEND_MODE, format_message

logger = logging.getLogger("router")


@dataclass
class Eligibility:
    group: TelegramGroup
    setting: GroupStrategySetting
    eligible: bool
    skip_code: str | None = None


def _skip_codes():
    return {
        "GROUP_INACTIVE", "BELOW_MIN_CONFIDENCE", "SYMBOL_NOT_ALLOWED",
        "TIMEFRAME_NOT_ALLOWED", "STRATEGY_MISMATCH", "GROUP_COOLDOWN_ACTIVE",
    }


def _cooldown_active(db: Session, setting: GroupStrategySetting, signal: Signal) -> bool:
    """True if the group sent/queued the same setup within cooldown_minutes (05 §3, 04 §8)."""
    if setting.cooldown_minutes <= 0:
        return False
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=setting.cooldown_minutes)
    row = db.scalar(
        select(TelegramOutbox)
        .join(Signal, TelegramOutbox.signal_id == Signal.id)
        .where(
            TelegramOutbox.group_id == setting.group_id,
            TelegramOutbox.status != "SKIPPED",
            Signal.symbol == signal.symbol,
            Signal.strategy_code == signal.strategy_code,
            Signal.action == signal.action,
            Signal.timeframe == signal.timeframe,
        )
        .order_by(TelegramOutbox.created_at.desc())
        .limit(1)
    )
    if row is None:
        return False
    marker = row.sent_at or row.created_at
    return marker >= cutoff


def evaluate_groups(db: Session, signal: Signal) -> list[Eligibility]:
    """Evaluate every active group setting for this signal's strategy."""
    strategy = db.scalar(select(Strategy).where(Strategy.code == signal.strategy_code))
    settings = db.scalars(
        select(GroupStrategySetting).where(GroupStrategySetting.is_active.is_(True))
    ).all()

    results: list[Eligibility] = []
    for setting in settings:
        group = db.get(TelegramGroup, setting.group_id)
        if group is None or not group.is_active or group.is_paused:
            results.append(Eligibility(group, setting, False, "GROUP_INACTIVE"))
            continue
        if strategy is None or setting.strategy_id != strategy.id:
            results.append(Eligibility(group, setting, False, "STRATEGY_MISMATCH"))
            continue

        symbols = db.scalars(
            select(GroupStrategySymbol.symbol).where(GroupStrategySymbol.setting_id == setting.id)
        ).all()
        if signal.symbol not in symbols:
            results.append(Eligibility(group, setting, False, "SYMBOL_NOT_ALLOWED"))
            continue

        tfs = db.scalars(
            select(GroupStrategyTimeframe.timeframe).where(
                GroupStrategyTimeframe.setting_id == setting.id
            )
        ).all()
        if signal.timeframe not in tfs:
            results.append(Eligibility(group, setting, False, "TIMEFRAME_NOT_ALLOWED"))
            continue

        if signal.confidence is None or signal.confidence < setting.min_confidence:
            results.append(Eligibility(group, setting, False, "BELOW_MIN_CONFIDENCE"))
            continue

        if _cooldown_active(db, setting, signal):
            results.append(Eligibility(group, setting, False, "GROUP_COOLDOWN_ACTIVE"))
            continue

        results.append(Eligibility(group, setting, True))
    return results


def _add_event(db, signal_id, event_type, message, details=None):
    db.add(SignalEvent(signal_id=signal_id, event_type=event_type, message=message, details=details or {}))


def route_signal(db: Session, signal: Signal) -> list[TelegramOutbox]:
    """Create outbox rows for eligible groups. Idempotent by delivery_uid (05 §4)."""
    created: list[TelegramOutbox] = []
    for ev in evaluate_groups(db, signal):
        if not ev.eligible:
            _add_event(
                db, signal.id, "ROUTER_SKIPPED_GROUP",
                f"Skipped group {ev.group.id}: {ev.skip_code}",
                {"groupId": ev.group.id, "skipCode": ev.skip_code},
            )
            continue

        delivery_uid = f"{signal.signal_uid}:{ev.group.id}"
        send_mode = ev.setting.send_mode or DEFAULT_SEND_MODE.get(ev.group.type, "FULL")
        outbox = TelegramOutbox(
            delivery_uid=delivery_uid, signal_id=signal.id, group_id=ev.group.id,
            group_strategy_setting_id=ev.setting.id, status="PENDING",
            send_mode=send_mode, message_text=format_message(signal, send_mode),
        )
        sp = db.begin_nested()
        db.add(outbox)
        try:
            db.flush()
            sp.commit()
        except IntegrityError:
            sp.rollback()  # duplicate delivery_uid -> skip, not error (05 §4)
            continue
        _add_event(
            db, signal.id, "OUTBOX_CREATED", f"Outbox for group {ev.group.id}",
            {"groupId": ev.group.id, "deliveryUid": delivery_uid},
        )
        _add_event(
            db, signal.id, "ROUTER_MATCHED_GROUP", f"Matched group {ev.group.id}",
            {"groupId": ev.group.id},
        )
        created.append(outbox)

    if created:
        signal.status = "QUEUED"
        _add_event(db, signal.id, "SIGNAL_STATUS_UPDATED", "QUEUED", {"status": "QUEUED"})
    return created
