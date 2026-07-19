"""TradingView bar webhook (03 §4). Auth by path token + body secret, then ingest."""

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.api.errors import error_response
from app.db.session import get_db
from app.schemas.tradingview import BarPayload, TradingViewSignalPayload
from app.services import ingestion, tv_signals
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
    webhook_token: str, request: Request, db: Session = Depends(get_db)
) -> JSONResponse:
    """Ingest external direct signals or confirmations from TradingView (Phase A)."""
    body = await request.json()
    body_secret = body.get("secret", "") if isinstance(body, dict) else ""

    try:
        source = ingestion.authenticate(db, webhook_token, body_secret)
    except ingestion.IngestError as e:
        return error_response(e.status_code, e.code, e.message)

    try:
        payload = TradingViewSignalPayload.model_validate(body)
    except ValidationError as e:
        return error_response(400, "INVALID_PAYLOAD", e.errors(include_url=False))

    try:
        result = tv_signals.ingest_signal(db, source, payload)
    except tv_signals.UnknownSymbol as e:
        db.rollback()
        return error_response(400, "UNKNOWN_SYMBOL", str(e))

    return JSONResponse(result)
