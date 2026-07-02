"""Plain-text Telegram message formatting by send mode (05 §6).

MVP sends plain text (no Markdown/HTML) to avoid escaping bugs.
"""

DEFAULT_SEND_MODE = {"FREE": "BASIC", "VIP": "FULL", "SMC": "FULL", "INTERNAL": "FULL"}


def _reason_lines(reason: list[str] | None) -> str:
    return "\n".join(f"- {r}" for r in (reason or []))


def format_basic(signal) -> str:
    zone_low = signal.entry_zone_low or signal.entry
    zone_high = signal.entry_zone_high or signal.entry
    reason = "\n".join(signal.reason or []) or "Liquidity sweep detected."
    return (
        "FOREX SIGNAL\n\n"
        f"Pair: {signal.symbol}\n"
        f"Action: {signal.action}\n"
        f"Zone: {zone_low} - {zone_high}\n"
        f"Timeframe: {signal.timeframe}\n\n"
        f"Reason:\n{reason}\n\n"
        "Quan ly von can than."
    )


def format_full(signal) -> str:
    tp = signal.tp or []
    tp1 = tp[0] if len(tp) > 0 else "-"
    tp2 = tp[1] if len(tp) > 1 else "-"
    rr = f"{signal.risk_reward}" if signal.risk_reward is not None else "-"
    conf = f"{signal.confidence}%" if signal.confidence is not None else "-"
    return (
        "VIP FOREX SIGNAL\n\n"
        f"Pair: {signal.symbol}\n"
        f"Action: {signal.action}\n"
        f"Entry: {signal.entry}\n"
        f"SL: {signal.sl}\n"
        f"TP1: {tp1}\n"
        f"TP2: {tp2}\n"
        f"RR: {rr}\n"
        f"Timeframe: {signal.timeframe}\n"
        f"Strategy: {signal.strategy_code}\n"
        f"Confidence: {conf}\n\n"
        f"Reason:\n{_reason_lines(signal.reason)}\n\n"
        f"Invalid if:\n{signal.invalid_if}\n\n"
        "Khong phai loi khuyen tai chinh."
    )


def format_message(signal, send_mode: str) -> str:
    if send_mode == "BASIC":
        return format_basic(signal)
    if send_mode in ("FULL", "SUMMARY"):
        return format_full(signal)
    return format_full(signal)
