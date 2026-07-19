"""Run a strategy for one trigger candle: context -> detect -> risk -> dup -> persist.

This is the Milestone C pipeline up to APPROVED. Router/outbox is Milestone D.
"""

import logging
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import MarketCandle, SignalEvent, SymbolSetting
from app.services.execution import maybe_generate_execution_ticket
from app.models.signals import Signal as SignalModel
from app.strategy.indicators import session_label
from app.strategy.liquidity_sweep import InsufficientTrendData
from app.strategy.registry import get_strategy
from app.strategy.risk import build_signal_uid, check_risk
from app.strategy.types import Candle, EventType, RejectCode, SignalCandidate, StrategyContext

logger = logging.getLogger("strategy")


def _load_candles(db: Session, source_id: int, symbol: str, timeframe: str, limit: int) -> list[Candle]:
    """Latest `limit` closed candles, returned oldest-first."""
    rows = db.scalars(
        select(MarketCandle)
        .where(
            MarketCandle.source_id == source_id,
            MarketCandle.symbol == symbol,
            MarketCandle.timeframe == timeframe,
            MarketCandle.is_closed.is_(True),
        )
        .order_by(MarketCandle.candle_time.desc())
        .limit(limit)
    ).all()
    rows.reverse()
    return [
        Candle(r.candle_time, r.open, r.high, r.low, r.close, r.volume) for r in rows
    ]


def _add_event(db: Session, signal_id: int, event_type: str, message: str, details: dict | None = None):
    db.add(SignalEvent(signal_id=signal_id, event_type=event_type, message=message, details=details or {}))


def _persist_reject(db: Session, symbol, timeframe, source_id, code, message, source_time, event_type) -> SignalModel:
    """Create a REJECTED signal row + event. Uses a synthetic uid so warmups are visible."""
    uid = f"reject:{symbol}:{timeframe}:{code}:{source_time.strftime('%Y-%m-%dT%H:%M:%SZ') if source_time else 'na'}"
    sig = SignalModel(
        signal_uid=uid, source_id=source_id, source="tradingview_bars",
        strategy_code="liquidity_sweep", symbol=symbol, timeframe=timeframe,
        action="BUY", status="REJECTED", reject_code=code, reject_message=message,
        source_candle_time=source_time,
    )
    sp = db.begin_nested()
    db.add(sig)
    try:
        db.flush()
        sp.commit()
    except IntegrityError:
        # A prior identical warmup/reject already exists; that is fine (idempotent).
        sp.rollback()
        return db.scalar(select(SignalModel).where(SignalModel.signal_uid == uid))
    _add_event(db, sig.id, event_type, message)
    return sig


def run_strategy(db: Session, *, symbol: str, timeframe: str, source_id: int, strategy_code: str = "liquidity_sweep") -> SignalModel | None:
    """Full pipeline for one trigger candle. Returns the persisted signal (or None if no setup)."""
    strategy = get_strategy(strategy_code)
    if strategy is None or timeframe not in strategy.trigger_timeframes:
        return None

    symbol_row = db.scalar(select(SymbolSetting).where(SymbolSetting.symbol == symbol))
    if symbol_row is None:
        return None

    # Load lookback candles per required timeframe.
    tf_candles: dict[str, list[Candle]] = {}
    for tf in strategy.required_timeframes:
        need = strategy.lookback(tf)
        candles = _load_candles(db, source_id, symbol, tf, need)
        if len(candles) < need:
            trigger_candles = _load_candles(db, source_id, symbol, timeframe, 1)
            st = trigger_candles[-1].candle_time if trigger_candles else None
            return _persist_reject(
                db, symbol, timeframe, source_id, RejectCode.INSUFFICIENT_HISTORY,
                f"Waiting for {tf} history ({len(candles)}/{need})", st, EventType.WARMUP_SKIPPED,
            )
        tf_candles[tf] = candles

    ctx = StrategyContext(
        symbol=symbol, trigger_timeframe=timeframe, timeframes=tf_candles,
        session=session_label(tf_candles[timeframe][-1].candle_time),
        spread=None,
        strategy_config={},
        symbol_config={
            "point_size": str(symbol_row.point_size),
            "sl_buffer_points": str(symbol_row.sl_buffer_points),
        },
    )

    try:
        candidates = strategy.detect(ctx)
    except InsufficientTrendData:
        st = tf_candles[timeframe][-1].candle_time
        return _persist_reject(
            db, symbol, timeframe, source_id, RejectCode.INSUFFICIENT_TREND_DATA,
            "EMA could not be computed", st, EventType.WARMUP_SKIPPED,
        )

    if not candidates:
        return None

    candidate = candidates[0]
    min_rr = Decimal(str(ctx.strategy_config.get("minRiskReward", "1.5")))
    reject_code = check_risk(candidate, min_rr=min_rr, spread=ctx.spread, max_spread=None)

    uid = build_signal_uid(
        candidate,
        point_size=Decimal(str(symbol_row.point_size)),
        entry_tolerance_points=Decimal("20"),
    )

    if reject_code:
        return _persist_signal(db, candidate, uid, source_id, status="REJECTED", reject_code=reject_code)

    # Call AI filter
    from app.services.ai_filter import safe_review
    ai_review = safe_review(db, candidate)
    candidate.metadata["ai_review"] = ai_review.model_dump(by_alias=True)
    
    if not ai_review.valid_signal:
        return _persist_signal(
            db, candidate, uid, source_id, status="REJECTED", reject_code="AI_REJECTED"
        )
        
    # Apply confidence adjustment
    candidate.confidence = ai_review.final_confidence
    if ai_review.risk_note:
        candidate.metadata["risk_note"] = ai_review.risk_note
    if ai_review.telegram_reason:
        candidate.metadata["telegram_reason"] = ai_review.telegram_reason

    sig = _persist_signal(db, candidate, uid, source_id, status="APPROVED")
    if sig and sig.status == "APPROVED":
        maybe_generate_execution_ticket(db, sig)
    return sig


def _persist_signal(db: Session, candidate: SignalCandidate, uid: str, source_id: int, *, status: str, reject_code: str | None = None) -> SignalModel | None:
    """Insert the signal; DB unique on signal_uid is the authoritative duplicate guard."""
    sig = SignalModel(
        signal_uid=uid, source_id=source_id, source="tradingview_bars",
        strategy_code=candidate.strategy_code, symbol=candidate.symbol,
        timeframe=candidate.timeframe, action=candidate.action,
        entry=candidate.entry, sl=candidate.sl,
        tp=[str(x) for x in candidate.tp],
        risk_reward=candidate.risk_reward, confidence=candidate.confidence,
        reason=candidate.reason, invalid_if=candidate.invalid_if,
        source_candle_time=candidate.source_candle_time, status=status,
        reject_code=reject_code, metadata_=candidate.metadata,
    )
    sp = db.begin_nested()  # SAVEPOINT: only undo this insert on conflict, not caller's work
    db.add(sig)
    try:
        db.flush()
        sp.commit()
    except IntegrityError:
        # Duplicate signal_uid -> mark skipped, no outbox (04 §7).
        sp.rollback()
        existing = db.scalar(select(SignalModel).where(SignalModel.signal_uid == uid))
        logger.info("duplicate_signal", extra={"extra_fields": {"uid": uid}})
        return existing

    _add_event(db, sig.id, EventType.SIGNAL_CREATED, "Signal candidate created")
    if status == "REJECTED":
        _add_event(db, sig.id, EventType.SIGNAL_REJECTED, f"Rejected: {reject_code}", {"rejectCode": reject_code})
    else:
        _add_event(db, sig.id, EventType.SIGNAL_APPROVED, "Passed global risk + duplicate guard")
    return sig
