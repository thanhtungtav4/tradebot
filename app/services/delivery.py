"""Telegram outbox worker: claim, send, retry, aggregate status (05 §7-§8)."""

import logging
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import Signal, SignalDelivery, SignalEvent, TelegramGroup, TelegramOutbox
from app.telegram.client import SendResult, send_message

logger = logging.getLogger("delivery")

BACKOFF_SECONDS = [30, 120, 300]  # 30s, 2m, 5m (05 §7)

# ponytail: single claim query does atomic lock; FOR UPDATE SKIP LOCKED prevents double-send.
_CLAIM_SQL = text("""
UPDATE telegram_outbox
SET status = 'SENDING', locked_by = :worker, lock_token = :lock,
    locked_until = NOW() + INTERVAL '2 minutes', updated_at = NOW()
WHERE id = (
  SELECT id FROM telegram_outbox
  WHERE (status IN ('PENDING','FAILED_RETRYABLE') AND next_attempt_at <= NOW()
         AND (locked_until IS NULL OR locked_until < NOW()))
     OR (status = 'SENDING' AND locked_until < NOW())
  ORDER BY next_attempt_at
  FOR UPDATE SKIP LOCKED
  LIMIT 1
)
RETURNING id
""")

_CLAIM_BY_ID_SQL = text("""
UPDATE telegram_outbox
SET status = 'SENDING', locked_by = :worker, lock_token = :lock,
    locked_until = NOW() + INTERVAL '2 minutes', updated_at = NOW()
WHERE id = :id
  AND (
    status IN ('PENDING','FAILED_RETRYABLE')
    OR (status = 'SENDING' AND locked_until < NOW())
  )
  AND next_attempt_at <= NOW()
  AND (locked_until IS NULL OR locked_until < NOW() OR status = 'SENDING')
RETURNING id
""")


def _add_event(db, signal_id, event_type, message, details=None):
    db.add(SignalEvent(signal_id=signal_id, event_type=event_type, message=message, details=details or {}))


def claim_one(db: Session, worker_id: str) -> TelegramOutbox | None:
    """Atomically claim a due/stale outbox row. Returns the locked row or None."""
    lock = secrets.token_hex(8)
    row_id = db.execute(_CLAIM_SQL, {"worker": worker_id, "lock": lock}).scalar()
    if row_id is None:
        return None
    return db.get(TelegramOutbox, row_id)


def claim_by_id(db: Session, outbox_id: int, worker_id: str) -> TelegramOutbox | None:
    """Atomically claim a specific due/stale row before a queued send job."""
    lock = secrets.token_hex(8)
    row_id = db.execute(
        _CLAIM_BY_ID_SQL, {"id": outbox_id, "worker": worker_id, "lock": lock}
    ).scalar()
    if row_id is None:
        return None
    return db.get(TelegramOutbox, row_id)


def _backoff(attempt_count: int) -> int:
    idx = min(attempt_count, len(BACKOFF_SECONDS) - 1)
    return BACKOFF_SECONDS[idx]


def _update_aggregate(db: Session, signal_id: int) -> None:
    """Set signal.status from its outbox rows (05 §7 SENT/PARTIAL/FAILED)."""
    rows = db.scalars(select(TelegramOutbox).where(TelegramOutbox.signal_id == signal_id)).all()
    if not rows:
        return
    statuses = [r.status for r in rows]
    sent = sum(s == "SENT" for s in statuses)
    perm = sum(s == "FAILED_PERMANENT" for s in statuses)
    pending = sum(s in ("PENDING", "SENDING", "FAILED_RETRYABLE") for s in statuses)

    if sent == len(rows):
        new = "SENT"
    elif sent and pending:
        new = "PARTIAL_SENT"
    elif sent and perm:
        new = "PARTIAL_FAILED"
    elif perm == len(rows):
        new = "FAILED"
    else:
        new = None

    if new:
        sig = db.get(Signal, signal_id)
        if sig and sig.status != new:
            sig.status = new
            _add_event(db, signal_id, "SIGNAL_STATUS_UPDATED", new, {"status": new})


def process_outbox_row(db: Session, outbox: TelegramOutbox) -> None:
    """Send (or reclaim) one claimed outbox row and update state + attempt log."""
    # Stale reclaim: if a prior attempt already got a message id, don't resend (05 §8).
    if outbox.telegram_message_id:
        outbox.status = "SENT"
        outbox.sent_at = outbox.sent_at or datetime.now(timezone.utc)
        outbox.locked_until = None
        outbox.lock_token = None
        outbox.locked_by = None
        db.flush()
        _update_aggregate(db, outbox.signal_id)
        return

    group = db.get(TelegramGroup, outbox.group_id)
    attempt_no = outbox.attempt_count + 1
    attempt = SignalDelivery(
        outbox_id=outbox.id, delivery_uid=outbox.delivery_uid, signal_id=outbox.signal_id,
        group_id=outbox.group_id, attempt_no=attempt_no, status="SENDING",
    )
    db.add(attempt)
    db.flush()

    result: SendResult = send_message(group.telegram_chat_id, outbox.message_text)

    outbox.attempt_count = attempt_no
    outbox.last_attempt_at = datetime.now(timezone.utc)
    outbox.locked_until = None
    outbox.lock_token = None
    outbox.locked_by = None
    attempt.finished_at = datetime.now(timezone.utc)
    attempt.http_status_code = result.http_status

    if result.ok:
        outbox.status = "SENT"
        outbox.sent_at = datetime.now(timezone.utc)
        outbox.telegram_message_id = result.message_id
        attempt.status = "SENT"
        attempt.telegram_message_id = result.message_id
        if group:
            group.last_sent_at = outbox.sent_at
            group.last_delivery_status = "SENT"
        _add_event(db, outbox.signal_id, "DELIVERY_SENT", f"Sent to group {outbox.group_id}",
                   {"groupId": outbox.group_id})
    elif result.permanent or attempt_no >= outbox.max_attempts:
        outbox.status = "FAILED_PERMANENT"
        outbox.last_error_code = result.error_code
        outbox.last_error_message = result.error_message
        attempt.status = "FAILED_PERMANENT"
        attempt.error_code = result.error_code
        attempt.error_message = result.error_message
        if group:
            group.last_delivery_status = "FAILED_PERMANENT"
        _add_event(db, outbox.signal_id, "DELIVERY_FAILED",
                   f"Permanent failure group {outbox.group_id}",
                   {"groupId": outbox.group_id, "errorCode": result.error_code})
    else:
        delay = result.retry_after or _backoff(attempt_no - 1)
        outbox.status = "FAILED_RETRYABLE"
        outbox.next_attempt_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
        outbox.last_error_code = result.error_code
        outbox.last_error_message = result.error_message
        attempt.status = "FAILED_RETRYABLE"
        attempt.error_code = result.error_code
        attempt.error_message = result.error_message

    db.flush()
    _update_aggregate(db, outbox.signal_id)
