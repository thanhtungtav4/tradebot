"""Session dependency for Admin Console routes: redirect to login if unauthenticated."""

from fastapi import Request
from fastapi.responses import RedirectResponse

from app.security.session import COOKIE_NAME, read_session


class RedirectToLogin(Exception):
    pass


def require_session(request: Request) -> dict:
    session = read_session(request.cookies.get(COOKIE_NAME))
    if session is None:
        raise RedirectToLogin()
    return session


async def redirect_to_login_handler(request: Request, exc: RedirectToLogin):
    return RedirectResponse("/admin/login", status_code=303)
