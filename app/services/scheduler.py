"""Maintenance scans (00 §5a): stale feeds, health cache and outbox retry."""

import logging
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import DataSourceFeed, TelegramOutbox
from app.services.health import ComponentCheck, data_feed_check, upsert_component_health

logger = logging.getLogger("scheduler")

# Due retryable/pending rows, or stale SENDING rows to reclaim (05 §7).
_DUE_SQL = text("""
SELECT id FROM telegram_outbox
WHERE (status IN ('PENDING','FAILED_RETRYABLE') AND next_attempt_at <= NOW()
       AND (locked_until IS NULL OR locked_until < NOW()))
   OR (status = 'SENDING' AND locked_until < NOW())
""")


def find_due_outbox_ids(db: Session) -> list[int]:
    return list(db.execute(_DUE_SQL).scalars())


def scan_outbox_retry(db: Session, enqueue) -> int:
    """Enqueue send_telegram jobs for due rows. `enqueue(outbox_id)` is the sink."""
    ids = find_due_outbox_ids(db)
    for oid in ids:
        enqueue(oid)
    if ids:
        logger.info("outbox_retry_scan", extra={"extra_fields": {"count": len(ids)}})
    return len(ids)


def count_pending_by_status(db: Session) -> dict[str, int]:
    """Admin overview helper (06 §9)."""
    rows = db.execute(
        select(TelegramOutbox.status, text("count(*)")).group_by(TelegramOutbox.status)
    ).all()
    return {status: n for status, n in rows}


def _feed_age_minutes(feed: DataSourceFeed, now: datetime) -> float | None:
    if feed.last_candle_time is None:
        return None
    return (now - feed.last_candle_time).total_seconds() / 60


def scan_stale_feeds(db: Session) -> int:
    """Update active feed status and cached data_feed component health.

    `WARMUP` and `PAUSED` are intentional states. They are preserved while fresh;
    stale/error states degrade the aggregate data feed component.
    """
    now = datetime.now(timezone.utc)
    changed = 0
    feeds = db.scalars(select(DataSourceFeed).where(DataSourceFeed.is_active.is_(True))).all()
    for feed in feeds:
        old = feed.status
        age = _feed_age_minutes(feed, now)
        if old == "PAUSED":
            new = "PAUSED"
        elif age is None:
            new = "UNKNOWN"
        elif age > feed.stale_after_minutes:
            new = "STALE"
        elif old in ("WARMUP", "ERROR"):
            # Keep WARMUP visible until strategy context marks it OK. Clear ERROR after
            # a fresh candle only if the ingest path already changed the state.
            new = old
        else:
            new = "OK"
        if new != old:
            feed.status = new
            feed.updated_at = now
            changed += 1

    check = data_feed_check(db)
    upsert_component_health(db, check)
    if changed:
        logger.info(
            "data_feed_stale_scan",
            extra={"extra_fields": {"changed": changed, "status": check.status}},
        )
    return changed


def mark_component(db: Session, code: str, status: str, summary: str, details=None) -> None:
    """Small worker helper for heartbeat-style component updates."""
    upsert_component_health(
        db,
        ComponentCheck(code, status, summary, details or {}),
    )


def scan_signal_outcomes(db: Session) -> int:
    """Automatically scans subsequent candles to determine Take Profit or Stop Loss outcomes (Phase E)."""
    from decimal import Decimal
    from app.models import Signal, SignalEvent, MarketCandle

    signals = db.scalars(
        select(Signal)
        .where(
            Signal.status == "APPROVED",
            ~Signal.metadata_.has_key("outcome")
        )
    ).all()
    
    scanned = 0
    for sig in signals:
        if not sig.tp or not sig.sl:
            continue
            
        candles = db.scalars(
            select(MarketCandle)
            .where(
                MarketCandle.symbol == sig.symbol,
                MarketCandle.timeframe == sig.timeframe,
                MarketCandle.candle_time > sig.source_candle_time,
                MarketCandle.is_closed.is_(True)
            )
            .order_by(MarketCandle.candle_time.asc())
        ).all()
        
        if not candles:
            continue
            
        tp = Decimal(str(sig.tp[0]))
        sl = Decimal(str(sig.sl))
        
        outcome_status = None
        outcome_reason = ""
        
        for c in candles:
            c_high = Decimal(str(c.high))
            c_low = Decimal(str(c.low))
            
            if sig.action == "BUY":
                if c_low <= sl:
                    outcome_status = "LOSS"
                    outcome_reason = f"Stop Loss hit at {c_low} on candle {c.candle_time}"
                    break
                if c_high >= tp:
                    outcome_status = "WIN"
                    outcome_reason = f"Take Profit 1 hit at {c_high} on candle {c.candle_time}"
                    break
            elif sig.action == "SELL":
                if c_high >= sl:
                    outcome_status = "LOSS"
                    outcome_reason = f"Stop Loss hit at {c_high} on candle {c.candle_time}"
                    break
                if c_low <= tp:
                    outcome_status = "WIN"
                    outcome_reason = f"Take Profit 1 hit at {c_low} on candle {c.candle_time}"
                    break
                    
        if not outcome_status and len(candles) >= 50:
            outcome_status = "EXPIRED"
            outcome_reason = "No target hit after 50 candles"
            
        if outcome_status:
            outcome = {
                "status": outcome_status,
                "reason": outcome_reason,
                "updated_at": datetime.now(timezone.utc).isoformat()
            }
            metadata = sig.metadata_.copy()
            metadata["outcome"] = outcome
            sig.metadata_ = metadata
            
            db.add(SignalEvent(
                signal_id=sig.id,
                event_type="SIGNAL_STATUS_UPDATED",
                message=f"Outcome automatically set to {outcome_status}: {outcome_reason}",
                details=outcome
            ))
            scanned += 1
            
    if scanned > 0:
        logger.info("scan_signal_outcomes_updated", extra={"extra_fields": {"count": scanned}})
        
    return scanned
