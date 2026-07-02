"""RQ worker job entrypoints. Jobs take minimal payloads (00 §5a)."""

import logging
import socket

from redis import Redis
from rq import Queue

from app.config.logging import correlation_id
from app.config.settings import get_settings
from app.db.session import SessionLocal
from app.models import Signal
from app.services import delivery, router, strategy_runner

logger = logging.getLogger("worker")


def _queue(name: str) -> Queue:
    return Queue(name, connection=Redis.from_url(get_settings().redis_url))


def run_strategy(payload: dict) -> None:
    """Signal queue job: run the strategy pipeline for one trigger candle."""
    if cid := payload.get("correlation_id"):
        correlation_id.set(cid)
    with SessionLocal() as db:
        sig = strategy_runner.run_strategy(
            db,
            symbol=payload["symbol"],
            timeframe=payload["timeframe"],
            source_id=payload["source_id"],
        )
        db.commit()
        if sig and sig.status == "APPROVED":
            _queue("signal").enqueue("app.workers.route_signal", {"signal_id": sig.id})
    logger.info(
        "run_strategy_done",
        extra={"extra_fields": {
            "symbol": payload["symbol"], "signalId": sig.id if sig else None,
            "status": sig.status if sig else "NO_SETUP",
        }},
    )


def route_signal(payload: dict) -> None:
    """Signal queue job: route an approved signal to eligible groups, enqueue sends."""
    with SessionLocal() as db:
        sig = db.get(Signal, payload["signal_id"])
        if sig is None or sig.status not in ("APPROVED", "QUEUED"):
            return
        outboxes = router.route_signal(db, sig)
        db.commit()
        for ob in outboxes:
            _queue("telegram").enqueue("app.workers.send_telegram", {"outbox_id": ob.id})
    logger.info("route_signal_done", extra={"extra_fields": {
        "signalId": payload["signal_id"], "outboxCount": len(outboxes),
    }})


def send_telegram(payload: dict) -> None:
    """Telegram queue job: deliver one outbox row (with retry state).

    The queued id is still claimed atomically before sending so duplicate retry
    jobs or multiple telegram workers cannot double-send the same outbox row.
    """
    with SessionLocal() as db:
        outbox = delivery.claim_by_id(
            db, payload["outbox_id"], worker_id=f"telegram:{socket.gethostname()}"
        )
        if outbox is None:
            return
        delivery.process_outbox_row(db, outbox)
        db.commit()


def scan_outbox_retry(_payload: dict | None = None) -> None:
    """Maintenance job: re-enqueue due/stale outbox rows."""
    from app.services.scheduler import scan_outbox_retry as scan

    with SessionLocal() as db:
        q = _queue("telegram")
        scan(db, lambda oid: q.enqueue("app.workers.send_telegram", {"outbox_id": oid}))


def scan_stale_feeds(_payload: dict | None = None) -> None:
    """Maintenance job: update data_source_feeds + component_health.data_feed."""
    from app.services.scheduler import scan_stale_feeds as scan

    with SessionLocal() as db:
        scan(db)
        db.commit()


def scan_component_health(_payload: dict | None = None) -> None:
    """Maintenance job: refresh cached component health rows."""
    from app.services.health import collect_health

    with SessionLocal() as db:
        collect_health(db, persist=True)
