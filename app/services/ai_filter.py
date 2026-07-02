"""AI Filter Service implementing LLM and heuristic-based signal validation and confidence adjustment (Phase Future D)."""

import logging
import httpx
from typing import Protocol
from sqlalchemy.orm import Session
from app.config.settings import get_settings
from app.schemas.ai_filter import AISignalReview
from app.strategy.types import SignalCandidate

logger = logging.getLogger("ai_filter")


class AIReviewer(Protocol):
    def review(self, candidate: SignalCandidate) -> AISignalReview:
        ...


class PassthroughReviewer:
    """Default reviewer that passes through unchanged attributes."""
    def review(self, candidate: SignalCandidate) -> AISignalReview:
        return AISignalReview(
            validSignal=True,
            confidenceAdjustment=0,
            finalConfidence=candidate.confidence,
            riskNote="Passthrough: AI review skipped.",
            telegramReason="Rule-based strategy validation."
        )


class LocalHeuristicReviewer:
    """Local reviewer using heuristics without external API dependencies."""
    def review(self, candidate: SignalCandidate) -> AISignalReview:
        adjustment = 5 if candidate.risk_reward > 2.0 else -5
        final_conf = max(0, min(100, candidate.confidence + adjustment))
        
        action_verb = "mua (BUY)" if candidate.action == "BUY" else "bán (SELL)"
        risk_note = f"Heuristics: Đảm bảo tỷ lệ Risk/Reward ({float(candidate.risk_reward):.2f}) tối ưu. Cân nhắc vào lệnh {action_verb}."
        reason = f"Heuristics: Signal RR > 2 ({candidate.risk_reward > 2.0}) -> điều chỉnh +5 confidence." if candidate.risk_reward > 2.0 else "Heuristics: RR <= 2 -> điều chỉnh -5 confidence."
        
        return AISignalReview(
            validSignal=True,
            confidenceAdjustment=adjustment,
            finalConfidence=final_conf,
            riskNote=risk_note,
            telegramReason=reason
        )


class LLMReviewer:
    """Reviewer calling an external OpenAI-compatible or local LLM endpoint."""
    def __init__(self, api_url: str, api_key: str, model: str):
        self.api_url = api_url
        self.api_key = api_key
        self.model = model

    def review(self, candidate: SignalCandidate) -> AISignalReview:
        prompt = f"""
        Analyze the following trading signal candidate:
        Symbol: {candidate.symbol}
        Action: {candidate.action}
        Timeframe: {candidate.timeframe}
        Entry: {float(candidate.entry)}
        Stop Loss: {float(candidate.sl)}
        Take Profit: {[float(x) for x in candidate.tp]}
        Risk/Reward: {float(candidate.risk_reward)}
        Base Confidence: {candidate.confidence}
        Rule Reasons: {candidate.reason}
        Invalid If: {candidate.invalid_if}

        Respond ONLY with a JSON object in this format:
        {{
            "validSignal": true/false,
            "confidenceAdjustment": int (from -20 to 20),
            "finalConfidence": int (from 0 to 100),
            "riskNote": "short advice in Vietnamese under 280 characters",
            "telegramReason": "short explanation in Vietnamese under 200 characters"
        }}
        """
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
            "temperature": 0.2
        }

        try:
            # Set strict timeout of 1.5 seconds as per latency budget rules
            resp = httpx.post(self.api_url, json=payload, headers=headers, timeout=1.5)
            if resp.status_code == 200:
                data = resp.json()
                choice = data["choices"][0]["message"]["content"]
                # Parse json from choices
                return AISignalReview.model_validate_json(choice)
            else:
                logger.error(f"LLM API returned error status: {resp.status_code}. Response: {resp.text}")
                raise RuntimeError("LLM API Error")
        except Exception as e:
            logger.warning(f"LLM review failed or timed out: {e}. Falling back to Heuristics.")
            # Fallback to LocalHeuristicReviewer on any exception
            return LocalHeuristicReviewer().review(candidate)


def safe_review(db: Session, candidate: SignalCandidate) -> AISignalReview:
    """Wrapper calling the configured reviewer safely and returning validated results."""
    settings = get_settings()

    if not settings.ai_filter_enabled or settings.ai_filter_provider == "off":
        return PassthroughReviewer().review(candidate)

    reviewer: AIReviewer
    if settings.ai_filter_provider == "passthrough":
        reviewer = PassthroughReviewer()
    elif settings.ai_filter_provider == "heuristic":
        reviewer = LocalHeuristicReviewer()
    elif settings.ai_filter_provider == "llm":
        if settings.ai_filter_api_url and settings.ai_filter_api_key:
            reviewer = LLMReviewer(
                api_url=settings.ai_filter_api_url,
                api_key=settings.ai_filter_api_key,
                model=settings.ai_filter_model
            )
        else:
            logger.warning("LLM API URL or Key missing in configuration. Falling back to Heuristics.")
            reviewer = LocalHeuristicReviewer()
    else:
        reviewer = PassthroughReviewer()

    try:
        review_result = reviewer.review(candidate)
        
        # Guard: Ensure final confidence is bounded correctly
        review_result.final_confidence = max(0, min(100, review_result.final_confidence))
        review_result.confidence_adjustment = max(-20, min(20, review_result.confidence_adjustment))
        
        return review_result
    except Exception as e:
        logger.error(f"AI Reviewer raised unexpected exception: {e}. Returning Passthrough fallback.")
        return PassthroughReviewer().review(candidate)
