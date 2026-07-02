"""FastAPI application factory."""

from fastapi import FastAPI

from app.api.admin import api_router as admin_api_router
from app.api.admin import router as admin_router
from app.api.errors import unhandled_exception_handler
from app.api.health import router as health_router
from app.api.middleware import CorrelationIdMiddleware
from app.api.webhooks import router as webhooks_router
from app.api.bridge import router as bridge_router
from app.config.logging import configure_logging
from app.config.settings import get_settings
from app.security.auth import AuthError, auth_error_handler
from app.security.session_dep import RedirectToLogin, redirect_to_login_handler


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(title="tradebot", version="0.1.0")
    app.add_middleware(CorrelationIdMiddleware)
    app.add_exception_handler(Exception, unhandled_exception_handler)
    app.add_exception_handler(AuthError, auth_error_handler)
    app.add_exception_handler(RedirectToLogin, redirect_to_login_handler)
    app.include_router(health_router)
    app.include_router(admin_api_router)
    app.include_router(admin_router)
    app.include_router(webhooks_router)
    app.include_router(bridge_router)
    return app


app = create_app()
