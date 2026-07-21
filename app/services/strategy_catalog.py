"""Catalog cách đánh cho UI + auto-guide TradingView (đợt 1).

Gom mọi strategy trong registry kèm metadata + danh sách alert TradingView cần
tạo (required_timeframes × recommended_symbols). Tái dùng tradingview_alert_json.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config.settings import get_settings
from app.models import BrokerSymbolMapping
from app.services.admin import tradingview_alert_json
from app.strategy.registry import all_strategies


def source_symbol_for(db: Session, canonical: str) -> str:
    """Broker symbol cho một canonical symbol; fallback = chính canonical."""
    row = db.scalar(
        select(BrokerSymbolMapping.broker_symbol).where(
            BrokerSymbolMapping.canonical_symbol == canonical,
            BrokerSymbolMapping.is_active.is_(True),
        )
    )
    return row or canonical


def strategy_catalog(db: Session) -> list[dict]:
    """Mọi cách đánh + metadata + alert TradingView cần tạo."""
    body_secret = get_settings().tradingview_body_secret
    out: list[dict] = []
    for strat in all_strategies():
        alerts = [
            {
                "symbol": sym,
                "timeframe": tf,
                "json": tradingview_alert_json(
                    body_secret, source_symbol_for(db, sym), tf
                ),
            }
            for sym in strat.recommended_symbols
            for tf in strat.required_timeframes
        ]
        out.append(
            {
                "code": strat.code,
                "name": strat.name,
                "tagline": strat.tagline,
                "description": strat.description,
                "style": strat.style,
                "recommended_symbols": strat.recommended_symbols,
                "required_timeframes": strat.required_timeframes,
                "alert_count": len(alerts),
                "alerts": alerts,
            }
        )
    return out
