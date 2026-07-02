"""Unit tests for AI Filter Engine (Phase Future D)."""

import pytest
from decimal import Decimal
from datetime import datetime, timezone
from app.schemas.ai_filter import AISignalReview
from app.services.ai_filter import (
    PassthroughReviewer,
    LocalHeuristicReviewer,
    safe_review
)
from app.strategy.types import SignalCandidate


@pytest.fixture
def candidate():
    return SignalCandidate(
        strategy_code="liquidity_sweep",
        symbol="XAUUSD",
        timeframe="M15",
        action="BUY",
        entry=Decimal("2000.0"),
        sl=Decimal("1990.0"),
        tp=[Decimal("2015.0"), Decimal("2030.0")],
        risk_reward=Decimal("2.0"),
        confidence=80,
        reason=["Sweep High"],
        invalid_if="Price breaks low",
        source_candle_time=datetime.now(timezone.utc)
    )


def test_ai_schema_validation():
    # Valid model validation
    res = AISignalReview.model_validate({
        "validSignal": True,
        "confidenceAdjustment": 10,
        "finalConfidence": 90,
        "riskNote": "Good trend alignment.",
        "telegramReason": "Confirm candle closed strong."
    })
    assert res.valid_signal is True
    assert res.confidence_adjustment == 10
    assert res.final_confidence == 90

    # Auto clamping for confidence adjustment (> 20)
    res_clamp = AISignalReview.model_validate({
        "validSignal": True,
        "confidenceAdjustment": 35,
        "finalConfidence": 85
    })
    assert res_clamp.confidence_adjustment == 20

    # Auto clamping for final confidence (> 100)
    res_clamp2 = AISignalReview.model_validate({
        "validSignal": True,
        "confidenceAdjustment": -5,
        "finalConfidence": 120
    })
    assert res_clamp2.final_confidence == 100


def test_passthrough_reviewer(candidate):
    res = PassthroughReviewer().review(candidate)
    assert res.valid_signal is True
    assert res.confidence_adjustment == 0
    assert res.final_confidence == candidate.confidence


def test_heuristic_reviewer(candidate):
    # If RR is 2.0, adjustment should be -5 (since not > 2.0)
    res = LocalHeuristicReviewer().review(candidate)
    assert res.valid_signal is True
    assert res.confidence_adjustment == -5
    assert res.final_confidence == 75

    # If RR is 2.5, adjustment should be +5
    candidate_high_rr = SignalCandidate(
        strategy_code="liquidity_sweep",
        symbol="XAUUSD",
        timeframe="M15",
        action="BUY",
        entry=Decimal("2000.0"),
        sl=Decimal("1990.0"),
        tp=[Decimal("2025.0")],
        risk_reward=Decimal("2.5"),
        confidence=80,
        reason=["Sweep High"],
        invalid_if="Price breaks low",
        source_candle_time=datetime.now(timezone.utc)
    )
    res_high = LocalHeuristicReviewer().review(candidate_high_rr)
    assert res_high.confidence_adjustment == 5
    assert res_high.final_confidence == 85


def test_safe_review_default_disabled(db, candidate, monkeypatch):
    monkeypatch.setenv("AI_FILTER_ENABLED", "False")
    from app.config.settings import get_settings
    get_settings.cache_clear()
    
    res = safe_review(db, candidate)
    assert res.valid_signal is True
    assert res.confidence_adjustment == 0
    assert "Passthrough" in res.risk_note


def test_safe_review_heuristic(db, candidate, monkeypatch):
    monkeypatch.setenv("AI_FILTER_ENABLED", "True")
    monkeypatch.setenv("AI_FILTER_PROVIDER", "heuristic")
    from app.config.settings import get_settings
    get_settings.cache_clear()
    
    res = safe_review(db, candidate)
    assert res.valid_signal is True
    assert res.confidence_adjustment == -5
    assert "Heuristics" in res.risk_note
