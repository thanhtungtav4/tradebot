"""Integration tests for TradingView Signal/Confirmation Mode (Phase A)."""

import pytest
from app.models import Signal, DataSource
from tests.conftest import TEST_WEBHOOK_TOKEN, TEST_BODY_SECRET

pytestmark = pytest.mark.integration


def test_tv_signal_ingestion_success(client, db, monkeypatch):
    # Enable heuristic AI filter for predictable testing
    monkeypatch.setenv("AI_FILTER_ENABLED", "True")
    monkeypatch.setenv("AI_FILTER_PROVIDER", "heuristic")
    from app.config.settings import get_settings
    get_settings.cache_clear()

    # Configure the source as an MT5 connector to also test Phase F integration
    source = db.query(DataSource).filter(DataSource.code == "tradingview_bars").first()
    assert source is not None
    source.type = "MT5_CONNECTOR"
    source.config = {
        "balance": 10000.0,
        "risk_percent": 1.0,
        "open_positions": 0,
        "max_open_positions": 5,
        "daily_pnl": 0.0
    }
    db.commit()

    # Payload for TradingView signal
    payload = {
        "secret": TEST_BODY_SECRET,
        "symbol": "XAUUSD",
        "timeframe": "M15",
        "action": "BUY",
        "entry": 2000.0,
        "sl": 1990.0,
        "tp": "2015.0,2030.0",
        "confidence": 85,
        "reason": "MACD Crossover",
        "invalidIf": "Price drops below SL"
    }

    url = f"/api/v1/webhooks/tradingview/signals/{TEST_WEBHOOK_TOKEN}"
    resp = client.post(url, json=payload)
    assert resp.status_code == 200
    
    data = resp.json()
    assert data["status"] == "APPROVED"
    assert data["enqueued"] is True
    assert "review" in data

    # Verify database state
    signal_id = data["signal_id"]
    sig = db.get(Signal, signal_id)
    assert sig is not None
    assert sig.status == "APPROVED"
    assert sig.confidence == 80  # Heuristic adjusted 85 down by -5 (RR <= 2.0)
    assert "ai_review" in sig.metadata_
    assert "execution_ticket" in sig.metadata_
    assert sig.metadata_["execution_ticket"]["status"] == "PENDING"


def test_tv_signal_duplicate_rejection(client, db):
    payload = {
        "secret": TEST_BODY_SECRET,
        "symbol": "XAUUSD",
        "timeframe": "M15",
        "action": "BUY",
        "entry": 2000.0,
        "sl": 1990.0,
        "tp": "2015.0,2030.0",
        "confidence": 85,
        "reason": "MACD Crossover",
        "invalidIf": "Price drops below SL"
    }

    url = f"/api/v1/webhooks/tradingview/signals/{TEST_WEBHOOK_TOKEN}"
    
    # First post
    resp1 = client.post(url, json=payload)
    assert resp1.status_code == 200
    id1 = resp1.json()["signal_id"]

    # Second post (duplicate) should return the existing signal
    resp2 = client.post(url, json=payload)
    assert resp2.status_code == 200
    assert resp2.json()["signal_id"] == id1
