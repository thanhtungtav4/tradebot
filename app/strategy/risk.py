"""Global risk manager + signal_uid builder (04 §3-§7). Pure functions."""

from decimal import Decimal

from app.strategy.types import RejectCode, SignalCandidate


def check_risk(
    candidate: SignalCandidate, *, min_rr: Decimal, spread: Decimal | None, max_spread: Decimal | None
) -> str | None:
    """Return a reject code if the candidate fails global risk, else None."""
    if candidate.entry is None or candidate.sl is None or not candidate.tp or not candidate.invalid_if:
        return RejectCode.MISSING_PRICE_FIELDS

    # Recompute RR from entry/sl/tp2 to guard against a bad candidate (04 §5).
    tp2 = candidate.tp[-1]
    if candidate.action == "BUY":
        risk = candidate.entry - candidate.sl
        reward = tp2 - candidate.entry
    else:
        risk = candidate.sl - candidate.entry
        reward = candidate.entry - tp2
    if risk <= 0 or reward <= 0:
        return RejectCode.INVALID_RR_MATH
    if reward / risk < min_rr:
        return RejectCode.RR_TOO_LOW

    # Spread filter only when spread is present (TradingView bars omit spread -> skip).
    if spread is not None and max_spread is not None and spread > max_spread:
        return RejectCode.SPREAD_TOO_HIGH

    return None


def build_signal_uid(candidate: SignalCandidate, *, point_size: Decimal, entry_tolerance_points: Decimal) -> str:
    """Deterministic uid: strategy:symbol:tf:action:sourceTime:entryBucket (04 §6)."""
    ts = candidate.source_candle_time.strftime("%Y-%m-%dT%H:%M:%SZ")
    bucket = int((candidate.entry / point_size / entry_tolerance_points).to_integral_value())
    return (
        f"{candidate.strategy_code}:{candidate.symbol}:{candidate.timeframe}:"
        f"{candidate.action}:{ts}:{bucket}"
    )
