"""Admin auth dependencies: Bearer API key (scripts) and session (browser)."""

from fastapi import Depends, Request

from app.api.errors import error_response
from app.config.settings import Settings, get_settings
from app.security.secrets import constant_time_equals


class AuthError(Exception):
    """Raised by auth deps; translated to a 401 JSON response by the handler."""


def require_api_key(request: Request, settings: Settings = Depends(get_settings)) -> None:
    """Reject unless Authorization: Bearer {ADMIN_API_KEY} matches (constant-time)."""
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme != "Bearer" or not token or not constant_time_equals(token, settings.admin_api_key):
        raise AuthError("Invalid or missing API key")


async def auth_error_handler(request: Request, exc: AuthError):
    return error_response(401, "UNAUTHORIZED", str(exc))
