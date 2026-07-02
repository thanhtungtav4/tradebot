"""Integration tests for auto-trading execution engine (Phase F)."""

import pytest
from decimal import Decimal
from app.models import Signal, DataSource
from app.services.execution import (
    calculate_trade_volume,
    generate_execution_ticket,
    validate_execution_limits,
    ExecutionLimitError
)
from tests.conftest import TEST_WEBHOOK_TOKEN

pytestmark = pytest.mark.integration


def test_volume_calculation():
    # Test standard lot volume calculation
    vol = calculate_trade_volume(
        entry=Decimal("2000.00"),
        sl=Decimal("1990.00"),
        point_size=Decimal("0.01"),
        balance=10000.0,
        risk_percent=1.0
    )
    # entry - sl = 10.00 / 0.01 = 1000 points.
    # risk amount = 1% of 10000 = $100.
    # volume = 100 / (1000 * 10) = 0.01 standard lot.
    assert vol == 0.01

    # Bigger balance
    vol_big = calculate_trade_volume(
        entry=Decimal("2000.00"),
        sl=Decimal("1990.00"),
        point_size=Decimal("0.01"),
        balance=50000.0,
        risk_percent=2.0
    )
    # risk amount = 2% of 50000 = $1000.
    # volume = 1000 / (1000 * 10) = 0.10.
    assert vol_big == 0.10


def test_execution_limits():
    source = DataSource(
        code="mt5_test",
        type="MT5_CONNECTOR",
        display_name="MT5 Test",
        is_active=True,
        config={
            "balance": 10000.0,
            "open_positions": 5,
            "max_open_positions": 5
        }
    )
    
    with pytest.raises(ExecutionLimitError) as exc:
        validate_execution_limits(source)
    assert "Open positions limit reached" in str(exc.value)

    # Test daily loss budget limit
    source.config = {
        "balance": 10000.0,
        "open_positions": 2,
        "max_open_positions": 5,
        "daily_pnl": -600.0,
        "daily_loss_budget": 500.0
    }
    with pytest.raises(ExecutionLimitError) as exc:
        validate_execution_limits(source)
    assert "Daily loss budget exceeded" in str(exc.value)


def test_execution_ticket_generation_and_api(client, db):
    # Fetch seeded source
    source = db.query(DataSource).filter(DataSource.code == "tradingview_bars").first()
    assert source is not None

    # Enable and change source to MT5_CONNECTOR for execution test
    source.type = "MT5_CONNECTOR"
    source.config = {
        "balance": 20000.0,
        "risk_percent": 1.0,
        "open_positions": 1,
        "max_open_positions": 5,
        "daily_pnl": 0.0
    }
    db.commit()

    # Create approved signal
    sig = Signal(
        signal_uid="exec-test-sig-1",
        source="tradingview_bars",
        strategy_code="liquidity_sweep",
        symbol="XAUUSD",
        timeframe="M15",
        action="BUY",
        entry=2000.0,
        sl=1990.0,
        tp=["2015.0"],
        risk_reward=1.5,
        confidence=80,
        invalid_if="Price breaks low",
        status="APPROVED"
    )
    db.add(sig)
    db.commit()

    # Generate ticket
    ticket = generate_execution_ticket(db, sig)
    assert ticket["status"] == "PENDING"
    assert ticket["volume"] > 0.0

    # Get pending orders via API
    url_pending = f"/api/v1/bridge/orders/pending/{TEST_WEBHOOK_TOKEN}"
    resp_pending = client.get(url_pending)
    assert resp_pending.status_code == 200
    orders = resp_pending.json()["orders"]
    assert len(orders) >= 1
    assert orders[0]["signal_id"] == sig.id
    assert orders[0]["status"] == "PENDING"

    # Fill the order via API
    url_fill = f"/api/v1/bridge/orders/{sig.id}/fill/{TEST_WEBHOOK_TOKEN}"
    payload = {
        "status": "FILLED",
        "fill_price": 2000.5,
        "ticket_no": 9876543
    }
    resp_fill = client.post(url_fill, json=payload)
    assert resp_fill.status_code == 200
    assert resp_fill.json()["execution_ticket"]["status"] == "FILLED"
    assert resp_fill.json()["execution_ticket"]["ticket_no"] == 9876543

    db.refresh(sig)
    assert sig.metadata_["execution_ticket"]["status"] == "FILLED"
