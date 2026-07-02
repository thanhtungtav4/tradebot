"""Schemas for MT4/MT5 bridge payload validation."""

from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class BridgeCandlePayload(BaseModel):
    secret: str = Field(..., description="DataSource body secret")
    symbol: str = Field(..., description="Broker-specific symbol (e.g. EURUSD)")
    timeframe: str = Field(..., description="M5, M15, H1, or H4")
    time: str = Field(..., description="ISO 8601 string or format parsed by ISO")
    open: float
    high: float
    low: float
    close: float
    volume: float
    account_id: Optional[str] = Field(None, description="Optional verified broker account ID")
    broker: Optional[str] = Field(None, description="Optional broker code verification")


class BridgeHeartbeatPayload(BaseModel):
    secret: str = Field(..., description="DataSource body secret")
    status: str = Field("OK", description="Current status of connector")
    details: Optional[Dict[str, Any]] = None
