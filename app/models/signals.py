"""Candles, signals, events, outbox, delivery attempts (06 §5.8-5.12)."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utc_now_column
from app.models.enums import (
    DELIVERY_ATTEMPT_STATUS,
    OUTBOX_STATUS,
    SEND_MODE,
    SIGNAL_ACTION,
    SIGNAL_STATUS,
    TIMEFRAME,
    in_check,
)


class MarketCandle(Base):
    __tablename__ = "market_candles"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("data_sources.id"), nullable=False
    )
    source_code: Mapped[str] = mapped_column(Text, nullable=False)
    broker: Mapped[str] = mapped_column(Text, nullable=False, server_default="TRADINGVIEW")
    account_id: Mapped[str | None] = mapped_column(Text)
    symbol: Mapped[str] = mapped_column(Text, ForeignKey("symbol_settings.symbol"), nullable=False)
    source_symbol: Mapped[str] = mapped_column(Text, nullable=False)
    timeframe: Mapped[str] = mapped_column(Text, nullable=False)
    candle_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    open: Mapped[float] = mapped_column(Numeric, nullable=False)
    high: Mapped[float] = mapped_column(Numeric, nullable=False)
    low: Mapped[float] = mapped_column(Numeric, nullable=False)
    close: Mapped[float] = mapped_column(Numeric, nullable=False)
    volume: Mapped[float | None] = mapped_column(Numeric)
    spread: Mapped[float | None] = mapped_column(Numeric)
    is_closed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    payload_hash: Mapped[str | None] = mapped_column(Text)
    raw_payload: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = utc_now_column()
    updated_at: Mapped[datetime] = utc_now_column(onupdate=True)

    __table_args__ = (
        UniqueConstraint(
            "source_id", "symbol", "timeframe", "candle_time", name="uq_candle_key"
        ),
        CheckConstraint(in_check("timeframe", TIMEFRAME), name="ck_candle_timeframe"),
        CheckConstraint("high >= low", name="ck_candle_high_low"),
        CheckConstraint("high >= open", name="ck_candle_high_open"),
        CheckConstraint("high >= close", name="ck_candle_high_close"),
        CheckConstraint("low <= open", name="ck_candle_low_open"),
        CheckConstraint("low <= close", name="ck_candle_low_close"),
        CheckConstraint("volume IS NULL OR volume >= 0", name="ck_candle_volume"),
        CheckConstraint("spread IS NULL OR spread >= 0", name="ck_candle_spread"),
    )


# ponytail: guard from 06 §5.9 - approved+ signals must carry full trade fields.
_SIGNAL_COMPLETE = (
    "status NOT IN ('APPROVED','ROUTED','QUEUED','SENT','PARTIAL_SENT','PARTIAL_FAILED') "
    "OR (entry IS NOT NULL AND sl IS NOT NULL AND tp IS NOT NULL "
    "AND risk_reward IS NOT NULL AND confidence IS NOT NULL AND invalid_if IS NOT NULL)"
)


class Signal(Base):
    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    signal_uid: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    source_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("data_sources.id"))
    source: Mapped[str] = mapped_column(Text, nullable=False)
    strategy_code: Mapped[str] = mapped_column(
        Text, ForeignKey("strategies.code"), nullable=False
    )
    symbol: Mapped[str] = mapped_column(Text, ForeignKey("symbol_settings.symbol"), nullable=False)
    timeframe: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    entry: Mapped[float | None] = mapped_column(Numeric)
    entry_zone_low: Mapped[float | None] = mapped_column(Numeric)
    entry_zone_high: Mapped[float | None] = mapped_column(Numeric)
    sl: Mapped[float | None] = mapped_column(Numeric)
    tp: Mapped[list | None] = mapped_column(JSONB)
    risk_reward: Mapped[float | None] = mapped_column(Numeric)
    confidence: Mapped[int | None] = mapped_column(Integer)
    reason: Mapped[list | None] = mapped_column(JSONB)
    invalid_if: Mapped[str | None] = mapped_column(Text)
    source_candle_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="CREATED")
    reject_code: Mapped[str | None] = mapped_column(Text)
    reject_message: Mapped[str | None] = mapped_column(Text)
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, server_default="{}"
    )
    raw_payload: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = utc_now_column()
    updated_at: Mapped[datetime] = utc_now_column(onupdate=True)

    __table_args__ = (
        CheckConstraint(in_check("timeframe", TIMEFRAME), name="ck_signal_timeframe"),
        CheckConstraint(in_check("action", SIGNAL_ACTION), name="ck_signal_action"),
        CheckConstraint(in_check("status", SIGNAL_STATUS), name="ck_signal_status"),
        CheckConstraint(
            "confidence IS NULL OR confidence BETWEEN 0 AND 100", name="ck_signal_confidence"
        ),
        CheckConstraint("risk_reward IS NULL OR risk_reward > 0", name="ck_signal_rr"),
        CheckConstraint("tp IS NULL OR jsonb_typeof(tp) = 'array'", name="ck_signal_tp_array"),
        CheckConstraint(
            "reason IS NULL OR jsonb_typeof(reason) = 'array'", name="ck_signal_reason_array"
        ),
        CheckConstraint(_SIGNAL_COMPLETE, name="ck_signal_complete_when_approved"),
    )


class SignalEvent(Base):
    __tablename__ = "signal_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    signal_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("signals.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    message: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = utc_now_column()


class TelegramOutbox(Base):
    __tablename__ = "telegram_outbox"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    delivery_uid: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    signal_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("signals.id", ondelete="CASCADE"), nullable=False
    )
    group_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("telegram_groups.id"), nullable=False
    )
    group_strategy_setting_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("group_strategy_settings.id")
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="PENDING")
    send_mode: Mapped[str] = mapped_column(Text, nullable=False, server_default="FULL")
    message_text: Mapped[str] = mapped_column(Text, nullable=False)
    parse_mode: Mapped[str | None] = mapped_column(Text)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="3")
    next_attempt_at: Mapped[datetime] = utc_now_column()
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(Text)
    last_error_message: Mapped[str | None] = mapped_column(Text)
    telegram_message_id: Mapped[str | None] = mapped_column(Text)
    locked_by: Mapped[str | None] = mapped_column(Text)
    lock_token: Mapped[str | None] = mapped_column(Text)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = utc_now_column()
    updated_at: Mapped[datetime] = utc_now_column(onupdate=True)

    __table_args__ = (
        CheckConstraint(in_check("status", OUTBOX_STATUS), name="ck_outbox_status"),
        CheckConstraint(in_check("send_mode", SEND_MODE), name="ck_outbox_send_mode"),
        CheckConstraint("attempt_count >= 0", name="ck_outbox_attempt_count"),
        CheckConstraint("max_attempts > 0", name="ck_outbox_max_attempts"),
        CheckConstraint("attempt_count <= max_attempts", name="ck_outbox_attempt_le_max"),
    )


class SignalDelivery(Base):
    __tablename__ = "signal_deliveries"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    outbox_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("telegram_outbox.id", ondelete="CASCADE"), nullable=False
    )
    delivery_uid: Mapped[str] = mapped_column(Text, nullable=False)
    signal_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("signals.id", ondelete="CASCADE"), nullable=False
    )
    group_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("telegram_groups.id"), nullable=False
    )
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    http_status_code: Mapped[int | None] = mapped_column(Integer)
    telegram_message_id: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    response_payload: Mapped[dict | None] = mapped_column(JSONB)
    started_at: Mapped[datetime] = utc_now_column()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = utc_now_column()

    __table_args__ = (
        UniqueConstraint("outbox_id", "attempt_no", name="uq_delivery_outbox_attempt"),
        CheckConstraint("attempt_no > 0", name="ck_delivery_attempt_no"),
        CheckConstraint(in_check("status", DELIVERY_ATTEMPT_STATUS), name="ck_delivery_status"),
        CheckConstraint(
            "http_status_code IS NULL OR http_status_code BETWEEN 100 AND 599",
            name="ck_delivery_http_status",
        ),
    )
