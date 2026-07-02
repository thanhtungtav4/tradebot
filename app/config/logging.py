"""Structured JSON logging with a correlation id pulled from a contextvar."""

import json
import logging
from contextvars import ContextVar

correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)

# ponytail: secret keys scrubbed from log extras; add more if new secrets appear.
_REDACT_KEYS = {"token", "secret", "password", "authorization", "api_key", "bot_token"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": correlation_id.get(),
        }
        for k, v in getattr(record, "extra_fields", {}).items():
            payload[k] = "***" if k.lower() in _REDACT_KEYS else v
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
