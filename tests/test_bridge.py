"""Integration tests for MT4/MT5 bridge routers (Phase Future B/C)."""

import pytest
from app.models import DataSource, BrokerSymbolMapping, DataSourceFeed
from app.security.secrets import sha256_hex

pytestmark = pytest.mark.integration


def test_bridge_mt5_candles(client, db):
    # Setup MT5 source in DB
    mt5_token = "mt5-token-12345678901234567890"
    mt5_secret = "mt5-secret-1234567890123456789"
    source = DataSource(
        code="mt5_test",
        type="MT5_CONNECTOR",
        display_name="MT5 Test Broker",
        broker="MetaQuotes",
        account_id="123456",
        webhook_token_hash=sha256_hex(mt5_token),
        body_secret_hash=sha256_hex(mt5_secret),
        is_active=True,
    )
    db.add(source)
    db.flush()

    # Add broker symbol mapping
    mapping = BrokerSymbolMapping(
        source_id=source.id,
        broker="MetaQuotes",
        canonical_symbol="XAUUSD",
        broker_symbol="OANDA:XAUUSD",
        is_active=True,
    )
    db.add(mapping)

    # Add data source feed
    feed = DataSourceFeed(
        source_id=source.id,
        canonical_symbol="XAUUSD",
        source_symbol="OANDA:XAUUSD",
        timeframe="M15",
        stale_after_minutes=35,
        status="UNKNOWN",
    )
    db.add(feed)
    db.commit()

    # Valid candle request
    payload = {
        "secret": mt5_secret,
        "symbol": "OANDA:XAUUSD",
        "timeframe": "M15",
        "time": "2026-07-01T15:00:00Z",
        "open": 2000.0,
        "high": 2010.0,
        "low": 1995.0,
        "close": 2005.0,
        "volume": 120,
        "account_id": "123456",
        "broker": "MetaQuotes"
    }

    url = f"/api/v1/bridge/mt5/candles/{mt5_token}"
    resp = client.post(url, json=payload)
    print("RESP JSON:", resp.json())
    assert resp.status_code == 200
    assert resp.json()["outcome"] == "created"
    
    # Check health status updated
    db.refresh(source)
    assert source.status == "OK"
    assert source.last_ok_at is not None

    # Mismatch account ID guard check
    payload_bad_acc = payload.copy()
    payload_bad_acc["account_id"] = "wrong-account"
    resp_bad_acc = client.post(url, json=payload_bad_acc)
    assert resp_bad_acc.status_code == 403
    assert resp_bad_acc.json()["error"]["code"] == "INVALID_ACCOUNT"

    # Mismatch broker guard check
    payload_bad_broker = payload.copy()
    payload_bad_broker["broker"] = "wrong-broker"
    resp_bad_broker = client.post(url, json=payload_bad_broker)
    assert resp_bad_broker.status_code == 403
    assert resp_bad_broker.json()["error"]["code"] == "INVALID_BROKER"

    # Wrong source type check (calling mt4 endpoint for mt5 source)
    url_wrong_type = f"/api/v1/bridge/mt4/candles/{mt5_token}"
    resp_wrong_type = client.post(url_wrong_type, json=payload)
    assert resp_wrong_type.status_code == 400
    assert resp_wrong_type.json()["error"]["code"] == "INVALID_SOURCE_TYPE"


def test_bridge_mt4_candles(client, db):
    # Setup MT4 source in DB
    mt4_token = "mt4-token-12345678901234567890"
    mt4_secret = "mt4-secret-1234567890123456789"
    source = DataSource(
        code="mt4_test",
        type="MT4_BRIDGE",
        display_name="MT4 Test Broker",
        broker="ICMarkets",
        account_id="789012",
        webhook_token_hash=sha256_hex(mt4_token),
        body_secret_hash=sha256_hex(mt4_secret),
        is_active=True,
    )
    db.add(source)
    db.flush()

    # Add broker symbol mapping
    mapping = BrokerSymbolMapping(
        source_id=source.id,
        broker="ICMarkets",
        canonical_symbol="XAUUSD",
        broker_symbol="OANDA:XAUUSD",
        is_active=True,
    )
    db.add(mapping)

    # Add data source feed
    feed = DataSourceFeed(
        source_id=source.id,
        canonical_symbol="XAUUSD",
        source_symbol="OANDA:XAUUSD",
        timeframe="M15",
        stale_after_minutes=35,
        status="UNKNOWN",
    )
    db.add(feed)
    db.commit()

    payload = {
        "secret": mt4_secret,
        "symbol": "OANDA:XAUUSD",
        "timeframe": "M15",
        "time": "2026-07-01T15:00:00Z",
        "open": 2000.0,
        "high": 2010.0,
        "low": 1995.0,
        "close": 2005.0,
        "volume": 120,
        "account_id": "789012",
        "broker": "ICMarkets"
    }

    url = f"/api/v1/bridge/mt4/candles/{mt4_token}"
    resp = client.post(url, json=payload)
    assert resp.status_code == 200
    assert resp.json()["outcome"] == "created"


def test_bridge_heartbeat(client, db):
    mt5_token = "mt5-token-hb"
    mt5_secret = "mt5-secret-hb"
    source = DataSource(
        code="mt5_hb_test",
        type="MT5_CONNECTOR",
        display_name="MT5 Heartbeat Test",
        broker="MetaQuotes",
        account_id="123",
        webhook_token_hash=sha256_hex(mt5_token),
        body_secret_hash=sha256_hex(mt5_secret),
        is_active=True,
    )
    db.add(source)
    db.commit()

    payload = {
        "secret": mt5_secret,
        "status": "DEGRADED",
        "details": {
            "error_code": "CONNECTION_LOST",
            "error_message": "Failed to connect to MT5 terminal"
        }
    }

    url = f"/api/v1/bridge/heartbeat/{mt5_token}"
    resp = client.post(url, json=payload)
    assert resp.status_code == 200
    assert resp.json()["status"] == "DEGRADED"

    db.refresh(source)
    assert source.status == "DEGRADED"
    assert source.last_error_code == "CONNECTION_LOST"
    assert source.last_error_message == "Failed to connect to MT5 terminal"
