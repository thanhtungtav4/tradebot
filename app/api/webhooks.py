"""TradingView bar webhook (03 §4). Auth by path token + body secret, then ingest."""

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.api.errors import error_response
from app.db.session import get_db
from app.schemas.tradingview import BarPayload
from app.services import ingestion
from app.services.queue import enqueue_run_strategy

router = APIRouter(prefix="/api/v1/webhooks")
logger = logging.getLogger("webhook")


@router.post("/tradingview/bars/{webhook_token}")
async def tradingview_bars(
    webhook_token: str, request: Request, db: Session = Depends(get_db)
) -> JSONResponse:
    body = await request.json()
    body_secret = body.get("secret", "") if isinstance(body, dict) else ""

    try:
        source = ingestion.authenticate(db, webhook_token, body_secret)
    except ingestion.IngestError as e:
        return error_response(e.status_code, e.code, e.message)

    try:
        payload = BarPayload.model_validate(body)
    except ValidationError as e:
        return error_response(400, "INVALID_PAYLOAD", e.errors(include_url=False))

    try:
        norm = ingestion.normalize(db, source, payload)
        candle, outcome = ingestion.upsert_candle(db, source, norm)
        ingestion.update_feed_freshness(db, source, norm)
        db.commit()
    except ingestion.IngestError as e:
        db.rollback()
        return error_response(e.status_code, e.code, e.message)

    enqueued = False
    if outcome in ("created", "updated"):
        enqueued = enqueue_run_strategy(
            norm["symbol"], norm["timeframe"], norm["candle_time"], source.id
        )

    logger.info(
        "bar_ingested",
        extra={"extra_fields": {
            "symbol": norm["symbol"], "timeframe": norm["timeframe"],
            "outcome": outcome, "enqueued": enqueued,
        }},
    )
    return JSONResponse(
        {"outcome": outcome, "candleId": candle.id, "enqueued": enqueued}
    )


@router.post("/tradingview/signals/{webhook_token}")
async def tradingview_signals(
    webhook_token: str,
    request: Request,
    db: Session = Depends(get_db)
) -> JSONResponse:
    """Ingest external direct signals or confirmations from TradingView (Phase A)."""
    body = await request.json()
    body_secret = body.get("secret", "") if isinstance(body, dict) else ""

    try:
        source = ingestion.authenticate(db, webhook_token, body_secret)
    except ingestion.IngestError as e:
        return error_response(e.status_code, e.code, e.message)

    from app.schemas.tradingview import TradingViewSignalPayload
    try:
        payload = TradingViewSignalPayload.model_validate(body)
    except ValidationError as e:
        return error_response(400, "INVALID_PAYLOAD", e.errors(include_url=False))

    from sqlalchemy import select
    from app.models import BrokerSymbolMapping, SymbolSetting
    
    # Resolve symbol mapping
    mapping = db.scalar(
        select(BrokerSymbolMapping).where(
            BrokerSymbolMapping.source_id == source.id,
            BrokerSymbolMapping.broker_symbol == payload.symbol,
        )
    )
    if mapping is None:
        mapping = db.scalar(
            select(BrokerSymbolMapping).where(
                BrokerSymbolMapping.source_id == source.id,
                BrokerSymbolMapping.canonical_symbol == payload.symbol,
            )
        )
    if mapping is None:
        return error_response(400, "UNKNOWN_SYMBOL", f"Unknown symbol: {payload.symbol!r}")

    # Compute risk reward ratio
    from decimal import Decimal
    tp1 = payload.tp[0]
    if payload.action == "BUY":
        risk = payload.entry - payload.sl
        reward = tp1 - payload.entry
    else:
        risk = payload.sl - payload.entry
        reward = payload.entry - tp1

    risk_reward = Decimal("1.5")
    if risk > 0 and reward > 0:
        risk_reward = reward / risk

    # Build SignalCandidate
    from app.strategy.types import SignalCandidate
    from datetime import datetime, timezone
    
    candidate = SignalCandidate(
        strategy_code="liquidity_sweep",
        symbol=mapping.canonical_symbol,
        timeframe=payload.timeframe,
        action=payload.action,
        entry=payload.entry,
        sl=payload.sl,
        tp=payload.tp,
        risk_reward=risk_reward,
        confidence=payload.confidence,
        reason=payload.reason,
        invalid_if=payload.invalid_if or "Price invalidation target hit",
        source_candle_time=datetime.now(timezone.utc)
    )

    # Perform AI review
    from app.services.ai_filter import safe_review
    review = safe_review(db, candidate)
    candidate.metadata["ai_review"] = review.model_dump(by_alias=True)

    # Build unique signal UID
    from app.strategy.risk import build_signal_uid
    symbol_setting = db.scalar(select(SymbolSetting).where(SymbolSetting.symbol == mapping.canonical_symbol))
    point_size = Decimal(str(symbol_setting.point_size)) if symbol_setting else Decimal("0.00001")
    
    uid = build_signal_uid(
        candidate,
        point_size=point_size,
        entry_tolerance_points=Decimal("20")
    )

    status = "APPROVED" if review.valid_signal else "REJECTED"
    reject_code = None if review.valid_signal else "AI_REJECTED"

    if review.valid_signal:
        candidate.confidence = review.final_confidence
        if review.risk_note:
            candidate.metadata["risk_note"] = review.risk_note
        if review.telegram_reason:
            candidate.metadata["telegram_reason"] = review.telegram_reason

    # Persist signal
    from app.services.strategy_runner import _persist_signal
    sig = _persist_signal(db, candidate, uid, source.id, status=status, reject_code=reject_code)
    
    db.commit()

    # Enqueue routing job if APPROVED
    enqueued = False
    if sig and sig.status == "APPROVED":
        from app.services.queue import enqueue_route_signal
        enqueued = enqueue_route_signal(sig.id)

    return JSONResponse({
        "status": sig.status if sig else "FAILED",
        "signal_id": sig.id if sig else None,
        "enqueued": enqueued,
        "review": review.model_dump(by_alias=True)
    })
