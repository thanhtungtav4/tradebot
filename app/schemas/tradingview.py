"""TradingView bar webhook payload (03 §4.1). Numeric fields may arrive as strings."""

from decimal import Decimal

from pydantic import BaseModel, Field, field_validator

# timeframe aliases -> canonical (MVP: M15, H1 only)
_TIMEFRAME_ALIASES = {
    "15": "M15", "15m": "M15", "m15": "M15", "M15": "M15",
    "60": "H1", "1h": "H1", "h1": "H1", "H1": "H1",
}


class BarPayload(BaseModel):
    secret: str
    source: str = "TRADINGVIEW"
    symbol: str
    timeframe: str
    time: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal | None = None
    is_closed: bool = Field(default=True, alias="isClosed")

    model_config = {"populate_by_name": True}

    @field_validator("timeframe")
    @classmethod
    def _normalize_timeframe(cls, v: str) -> str:
        canonical = _TIMEFRAME_ALIASES.get(v.strip())
        if canonical is None:
            raise ValueError(f"Unsupported timeframe: {v!r} (MVP allows M15, H1)")
        return canonical

    @field_validator("is_closed")
    @classmethod
    def _must_be_closed(cls, v: bool) -> bool:
        if not v:
            raise ValueError("Only closed candles are accepted (isClosed must be true)")
        return v


class CandleImportPayload(BaseModel):
    source: str = "TRADINGVIEW"
    symbol: str
    timeframe: str
    time: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal | None = None
    is_closed: bool = Field(default=True, alias="isClosed")

    model_config = {"populate_by_name": True}

    @field_validator("timeframe")
    @classmethod
    def _normalize_timeframe(cls, v: str) -> str:
        return BarPayload._normalize_timeframe(v)

    @field_validator("is_closed")
    @classmethod
    def _must_be_closed(cls, v: bool) -> bool:
        return BarPayload._must_be_closed(v)


class TradingViewSignalPayload(BaseModel):
    secret: str
    symbol: str
    timeframe: str
    action: str
    entry: Decimal
    sl: Decimal
    tp: list[Decimal]
    confidence: int = Field(80)
    reason: list[str] = Field(default_factory=list)
    invalid_if: str = Field("", alias="invalidIf")

    model_config = {"populate_by_name": True}

    @field_validator("timeframe")
    @classmethod
    def _normalize_timeframe(cls, v: str) -> str:
        return BarPayload._normalize_timeframe(v)

    @field_validator("action")
    @classmethod
    def _validate_action(cls, v: str) -> str:
        upper = v.strip().upper()
        if upper not in ("BUY", "SELL"):
            raise ValueError(f"Invalid action: {v!r}. Must be BUY or SELL.")
        return upper

    @field_validator("tp", mode="before")
    @classmethod
    def _validate_tp(cls, v: any) -> list[Decimal]:
        if isinstance(v, str):
            return [Decimal(x.strip()) for x in v.split(",") if x.strip()]
        if isinstance(v, list):
            return [Decimal(str(x)) for x in v]
        raise ValueError("tp must be a list of decimals or comma-separated string")

    @field_validator("reason", mode="before")
    @classmethod
    def _validate_reason(cls, v: any) -> list[str]:
        if isinstance(v, str):
            return [x.strip() for x in v.split(",") if x.strip()]
        if isinstance(v, list):
            return [str(x) for x in v]
        return []
