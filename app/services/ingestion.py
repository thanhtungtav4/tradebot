"""TradingView bar ingestion: auth, normalize, upsert, feed freshness (03 §4)."""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BrokerSymbolMapping, DataSource, DataSourceFeed, MarketCandle
from app.schemas.tradingview import BarPayload
from app.security.secrets import constant_time_equals, sha256_hex


class IngestError(Exception):
    """Validation/auth failure with a stable error code."""

    def __init__(self, code: str, message: str, status_code: int = 400):
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def authenticate(db: Session, webhook_token: str, body_secret: str) -> DataSource:
    """Match path token + body secret against data_sources hashes. Token first (401)."""
    token_hash = sha256_hex(webhook_token)
    source = db.scalar(
        select(DataSource).where(DataSource.webhook_token_hash == token_hash)
    )
    if source is None:
        raise IngestError("INVALID_WEBHOOK_TOKEN", "Invalid webhook token", 401)
    if not source.body_secret_hash or not constant_time_equals(
        sha256_hex(body_secret), source.body_secret_hash
    ):
        raise IngestError("INVALID_BODY_SECRET", "Invalid body secret", 401)
    return source


def _parse_utc(value: str) -> datetime:
    """Parse an ISO timestamp; assume UTC if no tzinfo."""
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise IngestError("BAD_TIMESTAMP", f"Unparseable time: {value!r}") from exc
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def normalize(db: Session, source: DataSource, payload: BarPayload) -> dict:
    """Map source symbol -> canonical, coerce time to UTC. Raises IngestError on unknown symbol."""
    mapping = db.scalar(
        select(BrokerSymbolMapping).where(
            BrokerSymbolMapping.source_id == source.id,
            BrokerSymbolMapping.broker_symbol == payload.symbol,
        )
    )
    if mapping is None:
        # also accept a canonical symbol sent directly
        mapping = db.scalar(
            select(BrokerSymbolMapping).where(
                BrokerSymbolMapping.source_id == source.id,
                BrokerSymbolMapping.canonical_symbol == payload.symbol,
            )
        )
    if mapping is None:
        raise IngestError("UNKNOWN_SYMBOL", f"Unknown symbol: {payload.symbol!r}")

    return {
        "symbol": mapping.canonical_symbol,
        "source_symbol": payload.symbol,
        "timeframe": payload.timeframe,
        "candle_time": _parse_utc(payload.time),
        "open": payload.open,
        "high": payload.high,
        "low": payload.low,
        "close": payload.close,
        "volume": payload.volume,
    }


def _ohlc_consistent(c: dict) -> bool:
    hi, lo, op, cl = c["high"], c["low"], c["open"], c["close"]
    return hi >= lo and hi >= op and hi >= cl and lo <= op and lo <= cl


def upsert_candle(db: Session, source: DataSource, norm: dict) -> tuple[MarketCandle, str]:
    """Insert or update by (source, symbol, timeframe, candle_time). Returns (row, outcome)."""
    if not _ohlc_consistent(norm):
        raise IngestError("INVALID_OHLC", "OHLC values are internally inconsistent")

    existing = db.scalar(
        select(MarketCandle).where(
            MarketCandle.source_id == source.id,
            MarketCandle.symbol == norm["symbol"],
            MarketCandle.timeframe == norm["timeframe"],
            MarketCandle.candle_time == norm["candle_time"],
        )
    )
    if existing is None:
        row = MarketCandle(
            source_id=source.id,
            source_code=source.code,
            broker=source.broker,
            **norm,
        )
        db.add(row)
        db.flush()
        return row, "created"

    changed = any(
        getattr(existing, k) != v
        for k, v in norm.items()
        if k in ("open", "high", "low", "close", "volume")
    )
    if changed:
        for k in ("open", "high", "low", "close", "volume"):
            setattr(existing, k, norm[k])
        db.flush()
        return existing, "updated"
    return existing, "noop"


def update_feed_freshness(db: Session, source: DataSource, norm: dict) -> None:
    """Mark the matching feed OK with latest candle time (03 §4.3)."""
    feed = db.scalar(
        select(DataSourceFeed).where(
            DataSourceFeed.source_id == source.id,
            DataSourceFeed.canonical_symbol == norm["symbol"],
            DataSourceFeed.timeframe == norm["timeframe"],
        )
    )
    if feed is None:
        return
    feed.last_candle_time = norm["candle_time"]
    feed.last_payload_received_at = datetime.now(timezone.utc)
    feed.status = "OK"
    feed.last_error_code = None
    feed.last_error_message = None
    db.flush()
