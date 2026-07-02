"""Standard API error response shape."""

from fastapi import Request
from fastapi.responses import JSONResponse

from app.config.logging import correlation_id


def error_response(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {"code": code, "message": message},
            "correlationId": correlation_id.get(),
        },
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    return error_response(500, "INTERNAL_ERROR", "Internal server error")
