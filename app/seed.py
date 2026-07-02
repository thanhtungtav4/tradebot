"""Deterministic, repeat-safe MVP seed (06 §7). Run: python -m app.seed"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config.settings import get_settings
from app.db.session import SessionLocal
from app.security.secrets import sha256_hex
from app.models import (
    BrokerSymbolMapping,
    ComponentHealth,
    DataSource,
    DataSourceFeed,
    GroupStrategySetting,
    GroupStrategySymbol,
    GroupStrategyTimeframe,
    Strategy,
    SymbolSetting,
    TelegramGroup,
)
from app.models.enums import COMPONENT_CODES

SYMBOLS = [
    ("XAUUSD", "Gold / XAUUSD", 2, "0.01", "0.1", "20", "20"),
    ("EURUSD", "EUR/USD", 5, "0.00001", "0.0001", "20", "10"),
    ("GBPUSD", "GBP/USD", 5, "0.00001", "0.0001", "20", "10"),
]
# timeframe -> stale_after_minutes (bar length + STALE_GRACE_MINUTES from settings)
_BAR_MINUTES = {"M15": 15, "H1": 60}
FEED_TIMEFRAMES = ["M15", "H1"]
DEMO_GROUPS = [
    ("free_demo", "FREE", 75, "BASIC"),
    ("vip_demo", "VIP", 70, "FULL"),
    ("smc_demo", "SMC", 80, "FULL"),
]
LIQUIDITY_SWEEP_CONFIG = {
    "triggerTimeframe": "M15",
    "triggerTimeframes": ["M15"],
    "contextTimeframe": "H1",
    "swingLookback": 20,
    "confirmationCandles": 1,
    "minRiskReward": 1.5,
    "tp1R": 1.0,
    "tp2R": 2.0,
}


def _get_or_create(db: Session, model, defaults: dict | None = None, **keys):
    """Upsert by natural keys; update defaults if row exists. Returns row."""
    row = db.scalar(select(model).filter_by(**keys))
    if row is None:
        row = model(**keys, **(defaults or {}))
        db.add(row)
        db.flush()
    elif defaults:
        for k, v in defaults.items():
            setattr(row, k, v)
        db.flush()
    return row


def seed(db: Session) -> None:
    settings = get_settings()

    source = _get_or_create(
        db,
        DataSource,
        code="tradingview_bars",
        defaults={
            "type": "TRADINGVIEW_BAR_WEBHOOK",
            "display_name": "TradingView Bar Webhook",
            "broker": "TRADINGVIEW",
            "secret_ref": "TRADINGVIEW_WEBHOOK_TOKEN/TRADINGVIEW_BODY_SECRET",
            "webhook_token_hash": sha256_hex(settings.tradingview_webhook_token),
            "body_secret_hash": sha256_hex(settings.tradingview_body_secret),
            "stale_grace_minutes": settings.stale_grace_minutes,
            "status": "UNKNOWN",
        },
    )

    for sym, name, digits, point, pip, sl_buf, entry in SYMBOLS:
        _get_or_create(
            db,
            SymbolSetting,
            symbol=sym,
            defaults={
                "display_name": name,
                "price_digits": digits,
                "point_size": point,
                "pip_size": pip,
                "sl_buffer_points": sl_buf,
                "entry_zone_points": entry,
            },
        )
        _get_or_create(
            db,
            BrokerSymbolMapping,
            source_id=source.id,
            canonical_symbol=sym,
            defaults={"broker": "TRADINGVIEW", "broker_symbol": f"OANDA:{sym}"},
        )
        for tf in FEED_TIMEFRAMES:
            _get_or_create(
                db,
                DataSourceFeed,
                source_id=source.id,
                canonical_symbol=sym,
                timeframe=tf,
                defaults={
                    "source_symbol": f"OANDA:{sym}",
                    "stale_after_minutes": _BAR_MINUTES[tf] + settings.stale_grace_minutes,
                    "status": "UNKNOWN",
                },
            )

    strategy = _get_or_create(
        db,
        Strategy,
        code="liquidity_sweep",
        defaults={
            "name": "Liquidity Sweep",
            "version": "v1",
            "default_config": LIQUIDITY_SWEEP_CONFIG,
        },
    )

    for code, gtype, min_conf, send_mode in DEMO_GROUPS:
        group = _get_or_create(
            db,
            TelegramGroup,
            telegram_chat_id=f"PLACEHOLDER_{code}",
            defaults={
                "name": code,
                "type": gtype,
                "mode": "DEMO",
                "is_active": False,
            },
        )
        setting = _get_or_create(
            db,
            GroupStrategySetting,
            group_id=group.id,
            setting_code="liquidity_sweep_default",
            defaults={
                "display_name": "Liquidity Sweep Default",
                "strategy_id": strategy.id,
                "min_confidence": min_conf,
                "send_mode": send_mode,
                "cooldown_minutes": 30,
                "duplicate_window_minutes": 30,
                "min_rr": "1.5",
            },
        )
        for sym, *_ in SYMBOLS:
            _get_or_create(db, GroupStrategySymbol, setting_id=setting.id, symbol=sym)
        _get_or_create(db, GroupStrategyTimeframe, setting_id=setting.id, timeframe="M15")

    for code in COMPONENT_CODES:
        _get_or_create(db, ComponentHealth, component_code=code, defaults={"status": "UNKNOWN"})


def main() -> None:
    with SessionLocal() as db:
        seed(db)
        db.commit()
    print("Seed complete.")


if __name__ == "__main__":
    main()
