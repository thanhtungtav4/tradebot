#!/usr/bin/env python3
"""Verify the MT4 bridge contract without a MetaTrader 4 terminal.

Seeds a throwaway MT4_BRIDGE data source, then POSTs the exact JSON shape the
MQL4 EA builds (see MT4_Bridge_EA.mq4) at the live local backend. Proves the
EA->backend contract on macOS. Repeat-safe: it drops its own source first.

Run: uv run python scripts/bridge/mt4_verify.py
Needs Postgres up + migrated (make dev-services-up && make migrate).
"""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.session import SessionLocal  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models import (  # noqa: E402
    BrokerSymbolMapping,
    DataSource,
    DataSourceFeed,
)
from app.security.secrets import sha256_hex  # noqa: E402

CODE = "mt4_verify"
TOKEN = "mt4-verify-token-abcdefghijklmnop"
SECRET = "mt4-verify-secret-abcdefghijklmn"
BROKER = "ICMarkets"
ACCOUNT = "789012"


def _seed(db) -> None:
    # Repeat-safe by reuse, not delete: a prior run's source has FK children
    # (candles/signals). Reuse it instead of cascading deletes.
    if db.scalar(select(DataSource).where(DataSource.code == CODE)) is not None:
        return

    source = DataSource(
        code=CODE,
        type="MT4_BRIDGE",
        display_name="MT4 Verify Broker",
        broker=BROKER,
        account_id=ACCOUNT,
        webhook_token_hash=sha256_hex(TOKEN),
        body_secret_hash=sha256_hex(SECRET),
        is_active=True,
    )
    db.add(source)
    db.flush()
    db.add(
        BrokerSymbolMapping(
            source_id=source.id,
            broker=BROKER,
            canonical_symbol="XAUUSD",
            broker_symbol="OANDA:XAUUSD",
            is_active=True,
        )
    )
    db.add(
        DataSourceFeed(
            source_id=source.id,
            canonical_symbol="XAUUSD",
            source_symbol="OANDA:XAUUSD",
            timeframe="M15",
            stale_after_minutes=35,
            status="UNKNOWN",
        )
    )
    db.commit()


def _ea_payload() -> dict:
    """Exact JSON shape the MQL4 EA SendCandle() builds.

    Fixed candle_time so reruns upsert the same row (repeat-safe, no new signals).
    """
    iso = "2026-07-01T15:00:00Z"  # matches EA's TimeToStr("%Y-%m-%dT%H:%M:00Z")
    return {
        "secret": SECRET,
        "symbol": "OANDA:XAUUSD",
        "timeframe": "M15",
        "time": iso,
        "open": 2000.0,
        "high": 2010.0,
        "low": 1995.0,
        "close": 2005.0,
        "volume": 120,
        "account_id": ACCOUNT,
        "broker": BROKER,
    }


def main() -> int:
    with SessionLocal() as db:
        _seed(db)

    client = TestClient(create_app())
    url = f"/api/v1/bridge/mt4/candles/{TOKEN}"

    print("mt4_verify: sending EA-shaped candle")
    ok = client.post(url, json=_ea_payload())
    # noop = identical candle already stored (dedup); still a valid accepted contract.
    if ok.status_code != 200 or ok.json().get("outcome") not in ("created", "updated", "noop"):
        print(f"mt4_verify: FAIL candle {ok.status_code} {ok.text}")
        return 1
    print(f"mt4_verify: candle OK outcome={ok.json()['outcome']}")

    print("mt4_verify: sending EA-shaped heartbeat")
    hb = client.post(
        f"/api/v1/bridge/heartbeat/{TOKEN}",
        json={"secret": SECRET, "status": "OK", "details": {"message": "EA active"}},
    )
    if hb.status_code != 200:
        print(f"mt4_verify: FAIL heartbeat {hb.status_code} {hb.text}")
        return 1
    print(f"mt4_verify: heartbeat OK status={hb.json()['status']}")

    # Guard checks: wrong broker/account must be rejected (defense at boundary).
    bad = _ea_payload()
    bad["account_id"] = "wrong"
    r = client.post(url, json=bad)
    if r.status_code != 403 or r.json()["error"]["code"] != "INVALID_ACCOUNT":
        print(f"mt4_verify: FAIL account guard {r.status_code} {r.text}")
        return 1
    print("mt4_verify: account guard OK")

    print("mt4_verify: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
