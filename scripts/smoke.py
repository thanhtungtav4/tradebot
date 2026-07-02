"""Local smoke test for Milestone F release readiness.

Runs in-process against configured Postgres/Redis. It does not require a live
Telegram token and does not send trading messages.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config.settings import get_settings  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models import DataSourceFeed, MarketCandle  # noqa: E402
from app.seed import seed  # noqa: E402


def _bar(secret: str) -> dict:
    return {
        "secret": secret,
        "symbol": "OANDA:XAUUSD",
        "timeframe": "M15",
        "time": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "open": "2000.0",
        "high": "2010.0",
        "low": "1995.0",
        "close": "2005.0",
        "volume": "100",
        "isClosed": True,
    }


def main() -> int:
    settings = get_settings()
    print("smoke: seeding database")
    with SessionLocal() as db:
        seed(db)
        db.commit()

    client = TestClient(create_app())

    print("smoke: checking liveness")
    live = client.get("/api/v1/health/live")
    if live.status_code != 200:
        print(f"smoke: live failed: {live.text}")
        return 1

    print("smoke: checking readiness")
    ready = client.get("/api/v1/health/ready")
    if ready.status_code != 200:
        print(f"smoke: ready failed: {ready.text}")
        return 1

    print("smoke: sending fake TradingView bar")
    webhook = f"/api/v1/webhooks/tradingview/bars/{settings.tradingview_webhook_token}"
    response = client.post(webhook, json=_bar(settings.tradingview_body_secret))
    if response.status_code != 200:
        print(f"smoke: webhook failed: {response.status_code} {response.text}")
        return 1
    print(f"smoke: webhook outcome={response.json().get('outcome')}")

    with SessionLocal() as db:
        candles = db.scalar(select(MarketCandle).where(MarketCandle.symbol == "XAUUSD"))
        feed = db.scalar(
            select(DataSourceFeed).where(
                DataSourceFeed.canonical_symbol == "XAUUSD",
                DataSourceFeed.timeframe == "M15",
            )
        )
        if candles is None or feed is None or feed.last_candle_time is None:
            print("smoke: candle/feed verification failed")
            return 1

    print("smoke: checking full health")
    health = client.get("/api/v1/health")
    print(f"smoke: health status={health.status_code} body_status={health.json().get('status')}")
    print("smoke: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
