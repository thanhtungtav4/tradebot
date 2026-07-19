"""TradingView direct-signal ingestion (Phase A). Resolve mapping -> candidate -> persist.

Extracted from the webhook handler so the route stays thin and this stays testable.
"""

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BrokerSymbolMapping, DataSource, SymbolSetting
from app.schemas.tradingview import TradingViewSignalPayload
from app.services.ai_filter import safe_review
from app.services.execution import maybe_generate_execution_ticket
from app.services.queue import enqueue_route_signal
from app.services.strategy_runner import _persist_signal
from app.strategy.risk import build_signal_uid
from app.strategy.types import SignalCandidate

_DEFAULT_RR = Decimal("1.5")
_DEFAULT_POINT_SIZE = Decimal("0.00001")
_ENTRY_TOLERANCE_POINTS = Decimal("20")


def _resolve_mapping(db: Session, source_id: int, symbol: str) -> BrokerSymbolMapping | None:
    """Match broker_symbol first, then canonical_symbol (payload may send either)."""
    for column in (BrokerSymbolMapping.broker_symbol, BrokerSymbolMapping.canonical_symbol):
        mapping = db.scalar(
            select(BrokerSymbolMapping).where(
                BrokerSymbolMapping.source_id == source_id, column == symbol
            )
        )
        if mapping is not None:
            return mapping
    return None


def _risk_reward(payload: TradingViewSignalPayload) -> Decimal:
    tp1 = payload.tp[0]
    if payload.action == "BUY":
        risk, reward = payload.entry - payload.sl, tp1 - payload.entry
    else:
        risk, reward = payload.sl - payload.entry, payload.entry - tp1
    if risk > 0 and reward > 0:
        return reward / risk
    return _DEFAULT_RR


def ingest_signal(db: Session, source: DataSource, payload: TradingViewSignalPayload) -> dict:
    """Persist an external TradingView signal. Returns the route response dict.

    Raises UnknownSymbol if the payload symbol has no broker mapping.
    """
    mapping = _resolve_mapping(db, source.id, payload.symbol)
    if mapping is None:
        raise UnknownSymbol(payload.symbol)

    candidate = SignalCandidate(
        strategy_code="liquidity_sweep",
        symbol=mapping.canonical_symbol,
        timeframe=payload.timeframe,
        action=payload.action,
        entry=payload.entry,
        sl=payload.sl,
        tp=payload.tp,
        risk_reward=_risk_reward(payload),
        confidence=payload.confidence,
        reason=payload.reason,
        invalid_if=payload.invalid_if or "Price invalidation target hit",
        source_candle_time=datetime.now(timezone.utc),
    )

    review = safe_review(db, candidate)
    candidate.metadata["ai_review"] = review.model_dump(by_alias=True)

    symbol_setting = db.scalar(
        select(SymbolSetting).where(SymbolSetting.symbol == mapping.canonical_symbol)
    )
    point_size = Decimal(str(symbol_setting.point_size)) if symbol_setting else _DEFAULT_POINT_SIZE
    uid = build_signal_uid(
        candidate, point_size=point_size, entry_tolerance_points=_ENTRY_TOLERANCE_POINTS
    )

    if review.valid_signal:
        status, reject_code = "APPROVED", None
        candidate.confidence = review.final_confidence
        if review.risk_note:
            candidate.metadata["risk_note"] = review.risk_note
        if review.telegram_reason:
            candidate.metadata["telegram_reason"] = review.telegram_reason
    else:
        status, reject_code = "REJECTED", "AI_REJECTED"

    sig = _persist_signal(db, candidate, uid, source.id, status=status, reject_code=reject_code)
    if sig and sig.status == "APPROVED":
        maybe_generate_execution_ticket(db, sig)
    db.commit()

    enqueued = False
    if sig and sig.status == "APPROVED":
        enqueued = enqueue_route_signal(sig.id)

    return {
        "status": sig.status if sig else "FAILED",
        "signal_id": sig.id if sig else None,
        "enqueued": enqueued,
        "review": review.model_dump(by_alias=True),
    }


class UnknownSymbol(Exception):
    """Payload symbol has no broker mapping for this source."""

    def __init__(self, symbol: str):
        self.symbol = symbol
        super().__init__(f"Unknown symbol: {symbol!r}")
