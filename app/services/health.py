"""Component health checks and cached health rows (09 §4, 07 plan)."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx
from redis import Redis
from rq import Queue, Worker
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.config.settings import Settings, get_settings
from app.models import ComponentHealth, DataSourceFeed
from app.models.enums import COMPONENT_CODES

QUEUE_COMPONENTS = {
    "market_worker": "market",
    "signal_worker": "signal",
    "telegram_worker": "telegram",
}


@dataclass
class ComponentCheck:
    code: str
    status: str
    summary: str
    details: dict[str, Any]
    latency_ms: float | None = None

    def as_response(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "status": self.status,
            "summary": self.summary,
            "details": self.details,
        }
        if self.latency_ms is not None:
            out["latencyMs"] = self.latency_ms
        return out


def upsert_component_health(db: Session, check: ComponentCheck) -> ComponentHealth:
    row = db.get(ComponentHealth, check.code)
    now = datetime.now(timezone.utc)
    if row is None:
        row = ComponentHealth(component_code=check.code)
        db.add(row)
    row.status = check.status
    row.summary = check.summary
    row.details = check.details
    row.checked_at = now
    row.updated_at = now
    if check.status == "OK":
        row.last_ok_at = now
    db.flush()
    return row


def check_db(db: Session) -> ComponentCheck:
    start = time.perf_counter()
    db.execute(text("SELECT 1"))
    return ComponentCheck(
        "db",
        "OK",
        "Database is reachable",
        {},
        round((time.perf_counter() - start) * 1000, 1),
    )


def redis_connection(settings: Settings | None = None) -> Redis:
    settings = settings or get_settings()
    return Redis.from_url(settings.redis_url)


def check_redis(settings: Settings | None = None) -> tuple[ComponentCheck, Redis | None]:
    start = time.perf_counter()
    try:
        conn = redis_connection(settings)
        conn.ping()
    except Exception as exc:  # noqa: BLE001
        return (
            ComponentCheck("redis", "DOWN", "Redis is not reachable", {"error": str(exc)[:200]}),
            None,
        )
    return (
        ComponentCheck(
            "redis",
            "OK",
            "Redis is reachable",
            {},
            round((time.perf_counter() - start) * 1000, 1),
        ),
        conn,
    )


def queue_depths(conn: Redis) -> dict[str, int]:
    depths = {}
    for name in ("market", "signal", "telegram", "maintenance"):
        try:
            depths[name] = Queue(name, connection=conn).count
        except Exception:  # noqa: BLE001
            depths[name] = -1
    return depths


def worker_checks(conn: Redis | None) -> list[ComponentCheck]:
    if conn is None:
        return [
            ComponentCheck(code, "UNKNOWN", "Redis unavailable; worker state unknown", {})
            for code in QUEUE_COMPONENTS
        ]
    try:
        workers = Worker.all(connection=conn)
    except Exception as exc:  # noqa: BLE001
        return [
            ComponentCheck(code, "UNKNOWN", "Cannot inspect RQ workers", {"error": str(exc)[:200]})
            for code in QUEUE_COMPONENTS
        ]

    active_queues_by_worker = {
        worker.name: [queue.name for queue in worker.queues] for worker in workers
    }
    checks = []
    for code, queue_name in QUEUE_COMPONENTS.items():
        matched = [
            name for name, queues in active_queues_by_worker.items() if queue_name in queues
        ]
        status = "OK" if matched else "DEGRADED"
        summary = (
            f"Worker consuming {queue_name} queue"
            if matched
            else f"No active worker consuming {queue_name} queue"
        )
        checks.append(
            ComponentCheck(code, status, summary, {"queue": queue_name, "workers": matched})
        )
    return checks


def scheduler_check(conn: Redis | None) -> ComponentCheck:
    if conn is None:
        return ComponentCheck("scheduler", "UNKNOWN", "Redis unavailable; scheduler unknown", {})
    # RQ scheduler heartbeat is not guaranteed in MVP. Treat Redis reachability as the
    # lightweight scheduler dependency and expose queue depths for operator context.
    return ComponentCheck(
        "scheduler",
        "OK",
        "Scheduler dependency is reachable",
        {"queueDepths": queue_depths(conn)},
    )


def data_feed_check(db: Session) -> ComponentCheck:
    feeds = db.scalars(
        select(DataSourceFeed).where(DataSourceFeed.is_active.is_(True))
    ).all()
    if not feeds:
        return ComponentCheck("data_feed", "UNKNOWN", "No active data feeds configured", {})
    counts: dict[str, int] = {}
    stale_or_error: list[str] = []
    unknown = 0
    for feed in feeds:
        counts[feed.status] = counts.get(feed.status, 0) + 1
        label = f"{feed.canonical_symbol} {feed.timeframe}"
        if feed.status in ("STALE", "ERROR"):
            stale_or_error.append(label)
        elif feed.status == "UNKNOWN":
            unknown += 1

    if stale_or_error:
        return ComponentCheck(
            "data_feed",
            "DEGRADED",
            "Some feeds are stale or errored",
            {"counts": counts, "affectedFeeds": stale_or_error[:20]},
        )
    if unknown == len(feeds):
        return ComponentCheck(
            "data_feed",
            "UNKNOWN",
            "No feed payload received yet",
            {"counts": counts},
        )
    return ComponentCheck("data_feed", "OK", "Active feeds are fresh", {"counts": counts})


def telegram_api_check(settings: Settings | None = None, conn: Redis | None = None) -> ComponentCheck:
    settings = settings or get_settings()
    cache_key = "tradebot:health:telegram_api"
    if conn is not None:
        cached = conn.get(cache_key)
        if cached:
            value = cached.decode("utf-8")
            status, _, summary = value.partition("|")
            return ComponentCheck("telegram_api", status, summary or "Cached Telegram health", {"cached": True})

    if "CHANGE_ME" in settings.telegram_bot_token:
        return ComponentCheck(
            "telegram_api",
            "UNKNOWN",
            "Telegram token is placeholder; live check skipped",
            {"cached": False},
        )

    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/getMe"
    try:
        response = httpx.get(url, timeout=settings.telegram_send_timeout_seconds)
        ok = response.status_code == 200 and response.json().get("ok") is True
    except Exception as exc:  # noqa: BLE001
        check = ComponentCheck(
            "telegram_api", "DEGRADED", "Telegram API check failed", {"error": str(exc)[:200]}
        )
    else:
        check = ComponentCheck(
            "telegram_api",
            "OK" if ok else "DEGRADED",
            "Telegram API reachable" if ok else "Telegram API returned an error",
            {"httpStatus": response.status_code},
        )

    if conn is not None:
        conn.setex(
            cache_key,
            settings.telegram_health_cache_seconds,
            f"{check.status}|{check.summary}",
        )
    return check


def collect_health(db: Session, *, persist: bool = True) -> tuple[str, dict[str, dict[str, Any]]]:
    settings = get_settings()
    checks: list[ComponentCheck] = [ComponentCheck("api", "OK", "API process is alive", {})]

    try:
        checks.append(check_db(db))
    except Exception as exc:  # noqa: BLE001
        checks.append(ComponentCheck("db", "DOWN", "Database check failed", {"error": str(exc)[:200]}))

    redis_check, conn = check_redis(settings)
    checks.append(redis_check)
    checks.append(data_feed_check(db))
    checks.extend(worker_checks(conn))
    checks.append(scheduler_check(conn))
    checks.append(telegram_api_check(settings, conn))

    by_code = {check.code: check for check in checks}
    for code in COMPONENT_CODES:
        by_code.setdefault(code, ComponentCheck(code, "UNKNOWN", "Not checked", {}))

    if persist:
        for check in by_code.values():
            upsert_component_health(db, check)
        db.commit()

    statuses = [check.status for check in by_code.values()]
    if "DOWN" in statuses:
        overall = "DOWN"
    elif any(status == "DEGRADED" for status in statuses):
        overall = "DEGRADED"
    elif any(status == "UNKNOWN" for status in statuses):
        overall = "DEGRADED"
    else:
        overall = "OK"

    return overall, {code: by_code[code].as_response() for code in sorted(by_code)}

