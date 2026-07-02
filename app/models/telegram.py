"""Telegram groups, strategies, group strategy settings + child tables (06 §5.5-5.7b)."""

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
    GROUP_MODE,
    GROUP_TYPE,
    OUTBOX_STATUS,
    RISK_LEVEL,
    SEND_MODE,
    TIMEFRAME,
    in_check,
)


class TelegramGroup(Base):
    __tablename__ = "telegram_groups"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    telegram_chat_id: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False, server_default="FREE")
    mode: Mapped[str] = mapped_column(Text, nullable=False, server_default="DEMO")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    is_paused: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    last_test_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_delivery_status: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = utc_now_column()
    updated_at: Mapped[datetime] = utc_now_column(onupdate=True)

    __table_args__ = (
        CheckConstraint(in_check("type", GROUP_TYPE), name="ck_group_type"),
        CheckConstraint(in_check("mode", GROUP_MODE), name="ck_group_mode"),
        CheckConstraint(
            f"last_delivery_status IS NULL OR {in_check('last_delivery_status', OUTBOX_STATUS)}",
            name="ck_group_last_delivery_status",
        ),
    )


class Strategy(Base):
    __tablename__ = "strategies"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    code: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[str] = mapped_column(Text, nullable=False, server_default="v1")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    default_config: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = utc_now_column()
    updated_at: Mapped[datetime] = utc_now_column(onupdate=True)


class GroupStrategySetting(Base):
    __tablename__ = "group_strategy_settings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    setting_code: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    group_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("telegram_groups.id"), nullable=False
    )
    strategy_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("strategies.id"), nullable=False
    )
    min_confidence: Mapped[int] = mapped_column(Integer, nullable=False, server_default="70")
    risk_level: Mapped[str] = mapped_column(Text, nullable=False, server_default="MEDIUM")
    send_mode: Mapped[str] = mapped_column(Text, nullable=False, server_default="FULL")
    cooldown_minutes: Mapped[int] = mapped_column(Integer, nullable=False, server_default="30")
    duplicate_window_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="30"
    )
    entry_tolerance_points: Mapped[float] = mapped_column(
        Numeric, nullable=False, server_default="20"
    )
    min_rr: Mapped[float] = mapped_column(Numeric, nullable=False, server_default="1.5")
    max_spread: Mapped[float | None] = mapped_column(Numeric)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = utc_now_column()
    updated_at: Mapped[datetime] = utc_now_column(onupdate=True)

    __table_args__ = (
        UniqueConstraint("group_id", "setting_code", name="uq_gss_group_setting_code"),
        CheckConstraint("min_confidence BETWEEN 0 AND 100", name="ck_gss_min_confidence"),
        CheckConstraint(in_check("risk_level", RISK_LEVEL), name="ck_gss_risk_level"),
        CheckConstraint(in_check("send_mode", SEND_MODE), name="ck_gss_send_mode"),
        CheckConstraint("cooldown_minutes >= 0", name="ck_gss_cooldown"),
        CheckConstraint("duplicate_window_minutes >= 0", name="ck_gss_dup_window"),
        CheckConstraint("entry_tolerance_points >= 0", name="ck_gss_entry_tol"),
        CheckConstraint("min_rr > 0", name="ck_gss_min_rr"),
        CheckConstraint("max_spread IS NULL OR max_spread >= 0", name="ck_gss_max_spread"),
    )


class GroupStrategySymbol(Base):
    __tablename__ = "group_strategy_symbols"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    setting_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("group_strategy_settings.id", ondelete="CASCADE"),
        nullable=False,
    )
    symbol: Mapped[str] = mapped_column(
        Text, ForeignKey("symbol_settings.symbol"), nullable=False
    )
    created_at: Mapped[datetime] = utc_now_column()

    __table_args__ = (
        UniqueConstraint("setting_id", "symbol", name="uq_gss_symbol"),
    )


class GroupStrategyTimeframe(Base):
    __tablename__ = "group_strategy_timeframes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    setting_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("group_strategy_settings.id", ondelete="CASCADE"),
        nullable=False,
    )
    timeframe: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = utc_now_column()

    __table_args__ = (
        UniqueConstraint("setting_id", "timeframe", name="uq_gss_timeframe"),
        CheckConstraint(in_check("timeframe", TIMEFRAME), name="ck_gss_tf_timeframe"),
    )
