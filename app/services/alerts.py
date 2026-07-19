"""O1: edge-triggered admin alerts. Page once when a component degrades, not every scan."""

import logging

from app.config.settings import get_settings
from app.telegram.client import send_message

logger = logging.getLogger("alerts")

_BAD = ("DOWN", "DEGRADED")  # UNKNOWN is a neutral startup state, not a failure.


def newly_degraded(old: dict[str, str], new: dict[str, str]) -> dict[str, str]:
    """Components that moved from a good state into DOWN/DEGRADED this cycle."""
    return {
        code: status
        for code, status in new.items()
        if status in _BAD and old.get(code) not in _BAD
    }


def notify_degraded(degraded: dict[str, str]) -> None:
    """Send one Telegram message to the admin alert chat. No-op if unconfigured."""
    if not degraded:
        return
    settings = get_settings()
    chat_id = settings.alert_telegram_chat_id
    if not chat_id or "CHANGE_ME" in settings.telegram_bot_token:
        logger.warning("component degraded but alerts unconfigured: %s", degraded)
        return
    lines = "\n".join(f"- {code}: {status}" for code, status in sorted(degraded.items()))
    send_message(chat_id, f"TRADEBOT ALERT\nComponent degraded:\n{lines}")
