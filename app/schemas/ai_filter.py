"""Schemas for AI filter reviews."""

from pydantic import BaseModel, Field, field_validator


class AISignalReview(BaseModel):
    valid_signal: bool = Field(True, alias="validSignal")
    confidence_adjustment: int = Field(0, alias="confidenceAdjustment")
    final_confidence: int = Field(..., alias="finalConfidence")
    risk_note: str = Field("", alias="riskNote", max_length=280)
    telegram_reason: str = Field("", alias="telegramReason", max_length=200)

    model_config = {"populate_by_name": True}

    @field_validator("confidence_adjustment")
    @classmethod
    def _clamp_adjustment(cls, v: int) -> int:
        return max(-20, min(20, v))

    @field_validator("final_confidence")
    @classmethod
    def _clamp_confidence(cls, v: int) -> int:
        return max(0, min(100, v))
