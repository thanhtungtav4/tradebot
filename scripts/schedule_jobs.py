"""Register recurring RQ scheduler maintenance jobs."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from redis import Redis  # noqa: E402
from rq_scheduler import Scheduler  # noqa: E402

from app.config.settings import get_settings  # noqa: E402


JOBS = (
    {
        "id": "tradebot_scan_outbox_retry",
        "func": "app.workers.scan_outbox_retry",
        "queue": "maintenance",
        "interval_setting": "retry_scan_interval_seconds",
        "default_interval": 20,
        "description": "Scan due/retryable/stale Telegram outbox rows",
    },
    {
        "id": "tradebot_scan_stale_feeds",
        "func": "app.workers.scan_stale_feeds",
        "queue": "maintenance",
        "interval": 60,
        "description": "Update data feed stale/warmup/ok status",
    },
    {
        "id": "tradebot_scan_component_health",
        "func": "app.workers.scan_component_health",
        "queue": "maintenance",
        "interval": 60,
        "description": "Refresh cached component health rows",
    },
)


def main() -> int:
    settings = get_settings()
    scheduler = Scheduler(connection=Redis.from_url(settings.redis_url))
    now = datetime.now(timezone.utc)

    for job in JOBS:
        interval = job.get("interval") or getattr(
            settings, job["interval_setting"], job["default_interval"]
        )
        try:
            scheduler.cancel(job["id"])
        except Exception:  # noqa: BLE001
            pass
        scheduler.schedule(
            scheduled_time=now + timedelta(seconds=5),
            func=job["func"],
            interval=interval,
            repeat=None,
            id=job["id"],
            description=job["description"],
            queue_name=job["queue"],
        )
        print(f"scheduled {job['id']} every {interval}s on {job['queue']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
