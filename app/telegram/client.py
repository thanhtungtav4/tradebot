"""Telegram sendMessage client (05 §7). Classifies transient vs permanent failures.

Token stays in the URL only; never logged.
"""

from dataclasses import dataclass

import httpx

from app.config.settings import get_settings


@dataclass
class SendResult:
    ok: bool
    permanent: bool  # True -> FAILED_PERMANENT, False -> retryable
    http_status: int | None
    message_id: str | None = None
    retry_after: int | None = None
    error_code: str | None = None
    error_message: str | None = None


def send_message(chat_id: str, text: str) -> SendResult:
    settings = get_settings()
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    try:
        resp = httpx.post(
            url,
            json={"chat_id": chat_id, "text": text},
            timeout=settings.telegram_send_timeout_seconds,
        )
    except httpx.HTTPError as exc:
        return SendResult(False, False, None, error_code="NETWORK", error_message=str(exc)[:200])

    if resp.status_code == 200 and resp.json().get("ok"):
        mid = str(resp.json()["result"]["message_id"])
        return SendResult(True, False, 200, message_id=mid)

    body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
    description = str(body.get("description", ""))[:200]

    if resp.status_code == 429:
        retry_after = body.get("parameters", {}).get("retry_after")
        return SendResult(False, False, 429, retry_after=retry_after,
                          error_code="RATE_LIMITED", error_message=description)
    if resp.status_code in (400, 403):
        # chat not found / bot blocked -> permanent
        return SendResult(False, True, resp.status_code,
                          error_code="PERMANENT", error_message=description)
    return SendResult(False, False, resp.status_code,
                      error_code="HTTP_ERROR", error_message=description)
