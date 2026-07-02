"""Unit tests for Telegram message formatter (05 §6). No DB."""

from types import SimpleNamespace

from app.telegram.formatter import DEFAULT_SEND_MODE, format_message


def _signal():
    return SimpleNamespace(
        symbol="XAUUSD", action="BUY", timeframe="M15", strategy_code="liquidity_sweep",
        entry="2325.50", sl="2318.00", tp=["2332.00", "2340.00"], risk_reward="1.8",
        confidence=82, reason=["Swept previous low", "M15 bullish confirmation"],
        invalid_if="M15 closes below 2318.00", entry_zone_low="2325.00", entry_zone_high="2327.00",
    )


def test_basic_mode_hides_entry_sl():
    msg = format_message(_signal(), "BASIC")
    assert "FOREX SIGNAL" in msg
    assert "Zone: 2325.00 - 2327.00" in msg
    assert "SL:" not in msg  # BASIC does not leak precise SL


def test_full_mode_shows_entry_sl_tp():
    msg = format_message(_signal(), "FULL")
    assert "Entry: 2325.50" in msg
    assert "SL: 2318.00" in msg
    assert "TP1: 2332.00" in msg
    assert "TP2: 2340.00" in msg
    assert "Confidence: 82%" in msg
    assert "M15 closes below 2318.00" in msg


def test_default_send_mode_mapping():
    assert DEFAULT_SEND_MODE["FREE"] == "BASIC"
    assert DEFAULT_SEND_MODE["VIP"] == "FULL"
    assert DEFAULT_SEND_MODE["SMC"] == "FULL"
