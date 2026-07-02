"""Signed session cookie + CSRF token using stdlib hmac. No external session lib.

Cookie value = base64(payload).base64(hmac). Payload = "username|expiry_epoch|csrf".
"""

import base64
import hmac
import json
import secrets
import time
from hashlib import sha256

from app.config.settings import get_settings

COOKIE_NAME = "admin_session"
_CSRF_BYTES = 32


def _sign(payload: bytes, key: str) -> str:
    sig = hmac.new(key.encode(), payload, sha256).digest()
    return f"{base64.urlsafe_b64encode(payload).decode()}.{base64.urlsafe_b64encode(sig).decode()}"


def _verify(token: str, key: str) -> bytes | None:
    try:
        raw_payload, raw_sig = token.split(".", 1)
        payload = base64.urlsafe_b64decode(raw_payload)
        sig = base64.urlsafe_b64decode(raw_sig)
    except (ValueError, Exception):  # noqa: BLE001
        return None
    expected = hmac.new(key.encode(), payload, sha256).digest()
    return payload if hmac.compare_digest(sig, expected) else None


def issue_session(username: str) -> str:
    settings = get_settings()
    expiry = int(time.time()) + settings.admin_session_ttl_hours * 3600
    csrf = secrets.token_urlsafe(_CSRF_BYTES)
    payload = json.dumps({"u": username, "exp": expiry, "csrf": csrf}).encode()
    return _sign(payload, settings.admin_session_secret)


def read_session(token: str | None) -> dict | None:
    """Return session dict if valid and unexpired, else None."""
    if not token:
        return None
    payload = _verify(token, get_settings().admin_session_secret)
    if payload is None:
        return None
    data = json.loads(payload)
    if data.get("exp", 0) < int(time.time()):
        return None
    return data
