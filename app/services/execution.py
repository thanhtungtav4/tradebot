"""Auto-Trading Execution Engine service (Phase Future F)."""

import logging
from decimal import Decimal
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import Signal, SignalEvent, DataSource, SymbolSetting

logger = logging.getLogger("execution")


class ExecutionLimitError(Exception):
    """Raised when execution limits (daily loss, position count) are violated."""
    pass


def validate_execution_limits(source: DataSource) -> None:
    """Check account limits reported by the broker connector via heartbeats."""
    config = source.config or {}
    
    # 1. Check open positions limit
    open_positions = int(config.get("open_positions", 0))
    max_positions = int(config.get("max_open_positions", 5))
    if open_positions >= max_positions:
        raise ExecutionLimitError(
            f"Blocked: Open positions limit reached ({open_positions}/{max_positions})"
        )

    # 2. Check daily loss budget limit
    daily_pnl = float(config.get("daily_pnl", 0.0))
    daily_loss_budget = float(config.get("daily_loss_budget", 500.0))
    if daily_pnl < 0 and abs(daily_pnl) >= daily_loss_budget:
        raise ExecutionLimitError(
            f"Blocked: Daily loss budget exceeded (PnL: {daily_pnl}$, Budget: {daily_loss_budget}$)"
        )


def calculate_trade_volume(
    entry: Decimal,
    sl: Decimal,
    point_size: Decimal,
    balance: float,
    risk_percent: float = 1.0,
    min_volume: float = 0.01,
    max_volume: float = 10.0
) -> float:
    """Calculate trade lot size volume based on account balance, risk percentage, and SL distance."""
    if entry == sl or point_size <= 0:
        return min_volume

    sl_distance = abs(entry - sl)
    sl_points = float(sl_distance / point_size)
    
    if sl_points <= 0:
        return min_volume

    # Assuming standard $10 value per standard lot per point for default conversion
    point_value = 10.0
    risk_amount = balance * (risk_percent / 100.0)
    
    volume = risk_amount / (sl_points * point_value)
    # Clamp volume between min_volume and max_volume
    volume = round(max(min_volume, min(max_volume, volume)), 2)
    return volume


def generate_execution_ticket(db: Session, signal: Signal) -> dict:
    """Generate and store trade execution ticket for MT4/MT5 bridge consumption."""
    # Find active broker datasource matching symbol or type
    # For simplicity, we find the first active MT4_BRIDGE or MT5_CONNECTOR
    source = db.scalar(
        select(DataSource)
        .where(
            DataSource.type.in_(["MT4_BRIDGE", "MT5_CONNECTOR"]),
            DataSource.is_active.is_(True)
        )
    )
    
    if not source:
        logger.warning("No active MT4/MT5 broker data source found for auto-execution.")
        return {}

    symbol_setting = db.scalar(
        select(SymbolSetting).where(SymbolSetting.symbol == signal.symbol)
    )
    point_size = Decimal(str(symbol_setting.point_size)) if symbol_setting else Decimal("0.00001")

    balance = float(source.config.get("balance", 10000.0))
    risk_percent = float(source.config.get("risk_percent", 1.0))

    ticket_status = "PENDING"
    error_msg = None
    volume = 0.01

    try:
        validate_execution_limits(source)
        
        # Calculate volume
        entry = Decimal(str(signal.entry))
        sl = Decimal(str(signal.sl))
        volume = calculate_trade_volume(entry, sl, point_size, balance, risk_percent)
        
    except ExecutionLimitError as e:
        ticket_status = "BLOCKED"
        error_msg = str(e)
        logger.warning(f"Signal {signal.id} execution blocked: {error_msg}")

    # Build execution ticket dict
    ticket = {
        "account_id": source.account_id or "demo-123",
        "broker": source.broker or "MT5",
        "symbol": signal.symbol,
        "action": signal.action,
        "entry": float(signal.entry),
        "sl": float(signal.sl),
        "tp": [float(x) for x in signal.tp] if signal.tp else [],
        "volume": volume,
        "status": ticket_status,
        "magic_number": int(source.config.get("magic_number", 9999)),
        "error_message": error_msg,
        "created_at": datetime.now(timezone.utc).isoformat()
    }

    # Save to signal metadata
    metadata = signal.metadata_.copy()
    metadata["execution_ticket"] = ticket
    signal.metadata_ = metadata

    # Record event
    event_msg = f"Execution ticket generated: status={ticket_status}, volume={volume}"
    if error_msg:
        event_msg += f" ({error_msg})"
    db.add(SignalEvent(
        signal_id=signal.id,
        event_type="SIGNAL_STATUS_UPDATED",
        message=event_msg,
        details=ticket
    ))
    
    db.flush()
    return ticket
