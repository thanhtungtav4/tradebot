"""All ORM models + indexes. Importing this registers everything on Base.metadata."""

from sqlalchemy import Index, text

from app.models.ops import AdminActivityLog, AppSetting, ComponentHealth
from app.models.signals import (
    MarketCandle,
    Signal,
    SignalDelivery,
    SignalEvent,
    TelegramOutbox,
)
from app.models.sources import (
    BrokerSymbolMapping,
    DataSource,
    DataSourceFeed,
    SymbolSetting,
)
from app.models.telegram import (
    GroupStrategySetting,
    GroupStrategySymbol,
    GroupStrategyTimeframe,
    Strategy,
    TelegramGroup,
)

__all__ = [
    "AdminActivityLog",
    "AppSetting",
    "BrokerSymbolMapping",
    "ComponentHealth",
    "DataSource",
    "DataSourceFeed",
    "GroupStrategySetting",
    "GroupStrategySymbol",
    "GroupStrategyTimeframe",
    "MarketCandle",
    "Signal",
    "SignalDelivery",
    "SignalEvent",
    "Strategy",
    "SymbolSetting",
    "TelegramGroup",
    "TelegramOutbox",
]

# Indexes from 06 §6. Partial indexes kept as raw postgresql_where text.
Index(
    "idx_data_source_feeds_status",
    DataSourceFeed.status,
    DataSourceFeed.is_active,
    DataSourceFeed.updated_at.desc(),
)
Index(
    "idx_data_source_feeds_matrix",
    DataSourceFeed.canonical_symbol,
    DataSourceFeed.timeframe,
    DataSourceFeed.source_id,
)
Index(
    "idx_broker_symbol_mappings_source_symbol",
    BrokerSymbolMapping.source_id,
    BrokerSymbolMapping.broker_symbol,
)
Index(
    "idx_group_strategy_settings_group_active",
    GroupStrategySetting.group_id,
    GroupStrategySetting.is_active,
)
Index(
    "idx_group_strategy_settings_strategy_active",
    GroupStrategySetting.strategy_id,
    GroupStrategySetting.is_active,
)
Index(
    "idx_group_strategy_symbols_symbol",
    GroupStrategySymbol.symbol,
    GroupStrategySymbol.setting_id,
)
Index("idx_group_strategy_symbols_setting", GroupStrategySymbol.setting_id)
Index(
    "idx_group_strategy_timeframes_timeframe",
    GroupStrategyTimeframe.timeframe,
    GroupStrategyTimeframe.setting_id,
)
Index("idx_group_strategy_timeframes_setting", GroupStrategyTimeframe.setting_id)
Index(
    "idx_market_candles_lookup",
    MarketCandle.symbol,
    MarketCandle.timeframe,
    MarketCandle.candle_time.desc(),
)
Index(
    "idx_market_candles_source_lookup",
    MarketCandle.source_id,
    MarketCandle.symbol,
    MarketCandle.timeframe,
    MarketCandle.candle_time.desc(),
)
Index(
    "idx_signals_lookup",
    Signal.symbol,
    Signal.timeframe,
    Signal.strategy_code,
    Signal.action,
    Signal.created_at.desc(),
)
Index("idx_signals_status_created", Signal.status, Signal.created_at.desc())
Index("idx_signal_events_signal", SignalEvent.signal_id, SignalEvent.created_at)
Index(
    "idx_telegram_outbox_pending",
    TelegramOutbox.status,
    TelegramOutbox.next_attempt_at,
    postgresql_where=text("status IN ('PENDING', 'FAILED_RETRYABLE')"),
)
Index(
    "idx_telegram_outbox_stale_lock",
    TelegramOutbox.locked_until,
    postgresql_where=text("status = 'SENDING'"),
)
Index("idx_telegram_outbox_signal", TelegramOutbox.signal_id)
Index(
    "idx_telegram_outbox_group_status",
    TelegramOutbox.group_id,
    TelegramOutbox.status,
    TelegramOutbox.created_at.desc(),
)
Index(
    "idx_signal_deliveries_outbox",
    SignalDelivery.outbox_id,
    SignalDelivery.attempt_no,
)
Index(
    "idx_signal_deliveries_status",
    SignalDelivery.status,
    SignalDelivery.created_at.desc(),
)
Index(
    "idx_admin_activity_logs_lookup",
    AdminActivityLog.resource_type,
    AdminActivityLog.resource_id,
    AdminActivityLog.created_at.desc(),
)
Index("idx_admin_activity_logs_created", AdminActivityLog.created_at.desc())
