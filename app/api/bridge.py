"""Bridge router for MT4/MT5 integrations (Phase Future B/C)."""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.api.errors import error_response
from app.db.session import get_db
from app.schemas.bridge import BridgeCandlePayload, BridgeHeartbeatPayload
from app.schemas.tradingview import BarPayload
from app.services import ingestion
from app.services.queue import enqueue_run_strategy

router = APIRouter(prefix="/api/v1/bridge")
logger = logging.getLogger("bridge")


@router.post("/mt5/candles/{webhook_token}")
async def mt5_candles(
    webhook_token: str, request: Request, db: Session = Depends(get_db)
) -> JSONResponse:
    """Ingest MT5 candle data."""
    body = await request.json()
    body_secret = body.get("secret", "") if isinstance(body, dict) else ""

    try:
        source = ingestion.authenticate(db, webhook_token, body_secret)
    except ingestion.IngestError as e:
        return error_response(e.status_code, e.code, e.message)

    if source.type != "MT5_CONNECTOR":
        return error_response(400, "INVALID_SOURCE_TYPE", "DataSource is not an MT5_CONNECTOR")

    try:
        payload = BridgeCandlePayload.model_validate(body)
    except ValidationError as e:
        return error_response(400, "INVALID_PAYLOAD", e.errors(include_url=False))

    # Guard: verify account_id and broker if configured
    if source.account_id and payload.account_id and source.account_id != payload.account_id:
        return error_response(403, "INVALID_ACCOUNT", "Account ID mismatch")
    if source.broker and source.broker != "TRADINGVIEW" and payload.broker and source.broker != payload.broker:
        return error_response(403, "INVALID_BROKER", "Broker mismatch")

    try:
        # Convert to BarPayload to reuse existing ingestion service
        bar = BarPayload(
            secret=payload.secret,
            symbol=payload.symbol,
            timeframe=payload.timeframe,
            time=payload.time,
            open=payload.open,
            high=payload.high,
            low=payload.low,
            close=payload.close,
            volume=payload.volume,
            isClosed=True,
        )
        norm = ingestion.normalize(db, source, bar)
        candle, outcome = ingestion.upsert_candle(db, source, norm)
        ingestion.update_feed_freshness(db, source, norm)
        
        # Update source metadata on successful feed
        source.status = "OK"
        source.last_ok_at = datetime.now(timezone.utc)
        source.last_payload_received_at = datetime.now(timezone.utc)
        source.last_error_code = None
        source.last_error_message = None
        
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
        "mt5_bar_ingested",
        extra={"extra_fields": {
            "symbol": norm["symbol"], "timeframe": norm["timeframe"],
            "outcome": outcome, "enqueued": enqueued,
        }},
    )
    return JSONResponse(
        {"outcome": outcome, "candleId": candle.id, "enqueued": enqueued}
    )


@router.post("/mt4/candles/{webhook_token}")
async def mt4_candles(
    webhook_token: str, request: Request, db: Session = Depends(get_db)
) -> JSONResponse:
    """Ingest MT4 candle data."""
    body = await request.json()
    body_secret = body.get("secret", "") if isinstance(body, dict) else ""

    try:
        source = ingestion.authenticate(db, webhook_token, body_secret)
    except ingestion.IngestError as e:
        return error_response(e.status_code, e.code, e.message)

    if source.type != "MT4_BRIDGE":
        return error_response(400, "INVALID_SOURCE_TYPE", "DataSource is not an MT4_BRIDGE")

    try:
        payload = BridgeCandlePayload.model_validate(body)
    except ValidationError as e:
        return error_response(400, "INVALID_PAYLOAD", e.errors(include_url=False))

    # Guard: verify account_id and broker if configured
    if source.account_id and payload.account_id and source.account_id != payload.account_id:
        return error_response(403, "INVALID_ACCOUNT", "Account ID mismatch")
    if source.broker and source.broker != "TRADINGVIEW" and payload.broker and source.broker != payload.broker:
        return error_response(403, "INVALID_BROKER", "Broker mismatch")

    try:
        # Convert to BarPayload to reuse existing ingestion service
        bar = BarPayload(
            secret=payload.secret,
            symbol=payload.symbol,
            timeframe=payload.timeframe,
            time=payload.time,
            open=payload.open,
            high=payload.high,
            low=payload.low,
            close=payload.close,
            volume=payload.volume,
            isClosed=True,
        )
        norm = ingestion.normalize(db, source, bar)
        candle, outcome = ingestion.upsert_candle(db, source, norm)
        ingestion.update_feed_freshness(db, source, norm)
        
        # Update source metadata on successful feed
        source.status = "OK"
        source.last_ok_at = datetime.now(timezone.utc)
        source.last_payload_received_at = datetime.now(timezone.utc)
        source.last_error_code = None
        source.last_error_message = None
        
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
        "mt4_bar_ingested",
        extra={"extra_fields": {
            "symbol": norm["symbol"], "timeframe": norm["timeframe"],
            "outcome": outcome, "enqueued": enqueued,
        }},
    )
    return JSONResponse(
        {"outcome": outcome, "candleId": candle.id, "enqueued": enqueued}
    )


@router.post("/heartbeat/{webhook_token}")
async def bridge_heartbeat(
    webhook_token: str, request: Request, db: Session = Depends(get_db)
) -> JSONResponse:
    """Receive heartbeat from MT4/MT5 bridge connectors."""
    body = await request.json()
    body_secret = body.get("secret", "") if isinstance(body, dict) else ""

    try:
        source = ingestion.authenticate(db, webhook_token, body_secret)
    except ingestion.IngestError as e:
        return error_response(e.status_code, e.code, e.message)

    try:
        payload = BridgeHeartbeatPayload.model_validate(body)
    except ValidationError as e:
        return error_response(400, "INVALID_PAYLOAD", e.errors(include_url=False))

    source.status = payload.status
    source.last_payload_received_at = datetime.now(timezone.utc)
    if payload.details:
        source.config = {**source.config, **payload.details}

    if payload.status == "OK":
        source.last_ok_at = datetime.now(timezone.utc)
        source.last_error_code = None
        source.last_error_message = None
    else:
        source.last_error_code = payload.details.get("error_code") if payload.details else "CONNECTOR_DEGRADED"
        source.last_error_message = payload.details.get("error_message") if payload.details else "Reported status not OK"

    db.commit()
    return JSONResponse({"status": source.status, "last_payload_received_at": source.last_payload_received_at.isoformat()})


@router.get("/orders/pending/{webhook_token}")
def get_pending_orders(
    webhook_token: str,
    db: Session = Depends(get_db)
) -> JSONResponse:
    """List pending signals for MT4/MT5 connectors to poll and execute (Phase F)."""
    from app.security.secrets import sha256_hex
    from app.models import DataSource
    from sqlalchemy import select
    
    token_hash = sha256_hex(webhook_token)
    source = db.scalar(
        select(DataSource).where(
            DataSource.webhook_token_hash == token_hash,
            DataSource.is_active.is_(True)
        )
    )
    if source is None:
        return error_response(401, "INVALID_WEBHOOK_TOKEN", "Invalid webhook token")
        
    if source.type not in ("MT4_BRIDGE", "MT5_CONNECTOR"):
        return error_response(400, "INVALID_SOURCE_TYPE", "DataSource is not an MT4/MT5 connector")

    from app.models import Signal
    
    signals = db.scalars(
        select(Signal)
        .where(
            Signal.status == "APPROVED",
            Signal.metadata_["execution_ticket"]["status"].astext == "PENDING"
        )
    ).all()
    
    orders = []
    for sig in signals:
        ticket = sig.metadata_["execution_ticket"]
        orders.append({
            "signal_id": sig.id,
            "signal_uid": sig.signal_uid,
            **ticket
        })
        
    return JSONResponse({"orders": orders})


@router.post("/orders/{signal_id}/fill/{webhook_token}")
async def fill_order(
    signal_id: int,
    webhook_token: str,
    request: Request,
    db: Session = Depends(get_db)
) -> JSONResponse:
    """Report execution outcome (fill price, ticket number, status) from broker (Phase F)."""
    body = await request.json()
    from app.security.secrets import sha256_hex
    from app.models import DataSource
    from sqlalchemy import select
    
    token_hash = sha256_hex(webhook_token)
    source = db.scalar(
        select(DataSource).where(
            DataSource.webhook_token_hash == token_hash,
            DataSource.is_active.is_(True)
        )
    )
    if source is None:
        return error_response(401, "INVALID_WEBHOOK_TOKEN", "Invalid webhook token")
        
    if source.type not in ("MT4_BRIDGE", "MT5_CONNECTOR"):
        return error_response(400, "INVALID_SOURCE_TYPE", "DataSource is not an MT4/MT5 connector")

    from app.models import Signal, SignalEvent
    sig = db.get(Signal, signal_id)
    if sig is None:
        return error_response(404, "SIGNAL_NOT_FOUND", f"Signal {signal_id} not found")
        
    if "execution_ticket" not in sig.metadata_:
        return error_response(400, "EXECUTION_TICKET_NOT_FOUND", "No execution ticket found on this signal")
        
    status = body.get("status")
    fill_price = body.get("fill_price")
    ticket_no = body.get("ticket_no")
    error_msg = body.get("error_message")

    if status not in ("FILLED", "REJECTED"):
        return error_response(400, "INVALID_EXECUTION_STATUS", "Status must be FILLED or REJECTED")

    metadata = sig.metadata_.copy()
    ticket = metadata["execution_ticket"].copy()
    ticket["status"] = status
    ticket["fill_price"] = fill_price
    ticket["ticket_no"] = ticket_no
    ticket["error_message"] = error_msg
    ticket["executed_at"] = datetime.now(timezone.utc).isoformat()
    metadata["execution_ticket"] = ticket
    sig.metadata_ = metadata

    msg = f"Order filled successfully: ticket_no={ticket_no}, fill_price={fill_price}" if status == "FILLED" else f"Order execution failed: {error_msg}"
    db.add(SignalEvent(
        signal_id=sig.id,
        event_type="SIGNAL_STATUS_UPDATED",
        message=msg,
        details=ticket
    ))
    
    db.commit()
    return JSONResponse({"status": "OK", "signal_id": signal_id, "execution_ticket": ticket})
