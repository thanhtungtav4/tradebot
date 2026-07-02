"""Data source, symbol, mapping and feed tables (06 §5.1-5.4)."""

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
from app.models.enums import COMPONENT_STATUS, DATA_SOURCE_TYPE, FEED_STATUS, TIMEFRAME, in_check


class DataSource(Base):
    __tablename__ = "data_sources"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    code: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    broker: Mapped[str] = mapped_column(Text, nullable=False, server_default="TRADINGVIEW")
    account_id: Mapped[str | None] = mapped_column(Text)
    secret_ref: Mapped[str | None] = mapped_column(Text)
    webhook_token_hash: Mapped[str | None] = mapped_column(Text)
    body_secret_hash: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="UNKNOWN")
    stale_grace_minutes: Mapped[int] = mapped_column(Integer, nullable=False, server_default="20")
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    last_ok_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_payload_received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(Text)
    last_error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = utc_now_column()
    updated_at: Mapped[datetime] = utc_now_column(onupdate=True)

    __table_args__ = (
        CheckConstraint(in_check("type", DATA_SOURCE_TYPE), name="ck_data_sources_type"),
        CheckConstraint(in_check("status", COMPONENT_STATUS), name="ck_data_sources_status"),
        CheckConstraint("stale_grace_minutes > 0", name="ck_data_sources_grace"),
    )


class SymbolSetting(Base):
    __tablename__ = "symbol_settings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    symbol: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    price_digits: Mapped[int] = mapped_column(Integer, nullable=False, server_default="2")
    point_size: Mapped[float] = mapped_column(Numeric, nullable=False)
    pip_size: Mapped[float | None] = mapped_column(Numeric)
    sl_buffer_points: Mapped[float] = mapped_column(Numeric, nullable=False, server_default="0")
    entry_zone_points: Mapped[float] = mapped_column(Numeric, nullable=False, server_default="0")
    max_spread: Mapped[float | None] = mapped_column(Numeric)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = utc_now_column()
    updated_at: Mapped[datetime] = utc_now_column(onupdate=True)

    __table_args__ = (
        CheckConstraint("price_digits BETWEEN 0 AND 8", name="ck_symbol_digits"),
        CheckConstraint("point_size > 0", name="ck_symbol_point_size"),
        CheckConstraint("pip_size IS NULL OR pip_size > 0", name="ck_symbol_pip_size"),
        CheckConstraint("sl_buffer_points >= 0", name="ck_symbol_sl_buffer"),
        CheckConstraint("entry_zone_points >= 0", name="ck_symbol_entry_zone"),
        CheckConstraint("max_spread IS NULL OR max_spread >= 0", name="ck_symbol_max_spread"),
    )


class BrokerSymbolMapping(Base):
    __tablename__ = "broker_symbol_mappings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("data_sources.id"), nullable=False
    )
    broker: Mapped[str] = mapped_column(Text, nullable=False, server_default="TRADINGVIEW")
    canonical_symbol: Mapped[str] = mapped_column(
        Text, ForeignKey("symbol_settings.symbol"), nullable=False
    )
    broker_symbol: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = utc_now_column()
    updated_at: Mapped[datetime] = utc_now_column(onupdate=True)

    __table_args__ = (
        UniqueConstraint("source_id", "canonical_symbol", name="uq_mapping_source_canonical"),
        UniqueConstraint("source_id", "broker_symbol", name="uq_mapping_source_broker"),
    )


class DataSourceFeed(Base):
    __tablename__ = "data_source_feeds"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("data_sources.id"), nullable=False
    )
    canonical_symbol: Mapped[str] = mapped_column(
        Text, ForeignKey("symbol_settings.symbol"), nullable=False
    )
    source_symbol: Mapped[str] = mapped_column(Text, nullable=False)
    timeframe: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="UNKNOWN")
    stale_after_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    last_candle_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_payload_received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(Text)
    last_error_message: Mapped[str | None] = mapped_column(Text)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = utc_now_column()
    updated_at: Mapped[datetime] = utc_now_column(onupdate=True)

    __table_args__ = (
        UniqueConstraint(
            "source_id", "canonical_symbol", "timeframe", name="uq_feed_source_symbol_tf"
        ),
        CheckConstraint(in_check("timeframe", TIMEFRAME), name="ck_feed_timeframe"),
        CheckConstraint(in_check("status", FEED_STATUS), name="ck_feed_status"),
        CheckConstraint("stale_after_minutes > 0", name="ck_feed_stale"),
    )
