"""Register exception handlers on the FastAPI app.

Domain exceptions from the service layer (app.core.exceptions) are mapped to HTTP
responses here, so services stay independent from the web layer. Any other
unhandled exception is turned into a consistent 500 JSON body (same `{"detail": ...}`
shape as the domain errors) instead of a plain-text "Internal Server Error".
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.exceptions import AppError
from app.core.logger import get_logger

logger = get_logger(__name__)


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    """Domain exception -> JSON response with its HTTP status."""
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


async def internal_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Any unhandled exception -> consistent 500 JSON body (logged with trace)."""
    logger.exception(f"Unhandled error on {request.method} {request.url.path}")
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


def register_exception_handlers(app: FastAPI) -> None:
    """Add the exception handlers to the app (called from create_app)."""
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(Exception, internal_error_handler)
