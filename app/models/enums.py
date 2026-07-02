"""Enum-like value sets. DB uses TEXT + CHECK; app references these constants.

Each is a plain tuple so it can feed both app validation and CHECK constraints.
"""

DATA_SOURCE_TYPE = (
    "TRADINGVIEW_BAR_WEBHOOK",
    "TRADINGVIEW_SIGNAL_WEBHOOK",
    "MT5_CONNECTOR",
    "MT4_BRIDGE",
    "OANDA",
)
COMPONENT_STATUS = ("UNKNOWN", "OK", "DEGRADED", "DOWN", "PAUSED")
FEED_STATUS = ("UNKNOWN", "WARMUP", "OK", "STALE", "ERROR", "PAUSED")
TIMEFRAME = ("M5", "M15", "H1", "H4")
GROUP_TYPE = ("FREE", "VIP", "SMC", "INTERNAL")
GROUP_MODE = ("DEMO", "INTERNAL", "LIVE")
SEND_MODE = ("BASIC", "FULL", "SUMMARY")
RISK_LEVEL = ("LOW", "MEDIUM", "HIGH")
SIGNAL_ACTION = ("BUY", "SELL")
SIGNAL_STATUS = (
    "CREATED",
    "REJECTED",
    "APPROVED",
    "ROUTED",
    "QUEUED",
    "SENT",
    "PARTIAL_SENT",
    "PARTIAL_FAILED",
    "FAILED",
    "SKIPPED_DUPLICATE",
)
OUTBOX_STATUS = (
    "PENDING",
    "SENDING",
    "SENT",
    "FAILED_RETRYABLE",
    "FAILED_PERMANENT",
    "SKIPPED",
)
DELIVERY_ATTEMPT_STATUS = ("SENDING", "SENT", "FAILED_RETRYABLE", "FAILED_PERMANENT")

COMPONENT_CODES = (
    "api",
    "db",
    "redis",
    "data_feed",
    "market_worker",
    "signal_worker",
    "telegram_worker",
    "scheduler",
    "telegram_api",
)


def in_check(column: str, values: tuple[str, ...]) -> str:
    """Render a SQL `col IN (...)` fragment for a CHECK constraint."""
    joined = ", ".join(f"'{v}'" for v in values)
    return f"{column} IN ({joined})"
