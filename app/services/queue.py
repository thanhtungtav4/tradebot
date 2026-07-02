"""Queue handoff for strategy jobs.

Webhook ingestion stays synchronous in MVP, then hands off trigger candles to RQ
using the worker import path contract from 00 §5a.
"""

import logging

from redis import Redis
from rq import Queue

from app.config.logging import correlation_id
from app.config.settings import get_settings

logger = logging.getLogger("queue")

# Liquidity Sweep v1 trigger timeframe (03 §4.4). H1 only updates context/freshness.
TRIGGER_TIMEFRAMES = {"M15"}


def enqueue_run_strategy(symbol: str, timeframe: str, candle_time, source_id: int) -> bool:
    """Enqueue if timeframe is a trigger. Returns True if enqueued. Never raises."""
    if timeframe not in TRIGGER_TIMEFRAMES:
        return False
    payload = {
        "symbol": symbol,
        "timeframe": timeframe,
        "candle_time": candle_time.isoformat(),
        "source_id": source_id,
        "correlation_id": correlation_id.get(),
    }
    try:
        q = Queue("signal", connection=Redis.from_url(get_settings().redis_url))
        q.enqueue("app.workers.run_strategy", payload)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("enqueue_failed", extra={"extra_fields": {"error": str(exc)[:200]}})
        return False


def enqueue_route_signal(signal_id: int) -> bool:
    """Enqueue signal routing job. Never raises."""
    try:
        q = Queue("signal", connection=Redis.from_url(get_settings().redis_url))
        q.enqueue("app.workers.route_signal", {"signal_id": signal_id})
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("enqueue_route_failed", extra={"extra_fields": {"error": str(exc)[:200]}})
        return False
