"""Register exception handlers on the FastAPI app.

Domain exceptions from the service layer (app.core.exceptions) are mapped to HTTP
responses here, so services stay independent from the web layer.
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.exceptions import AppError


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    """Domain exception -> JSON response with its HTTP status."""
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


def register_exception_handlers(app: FastAPI) -> None:
    """Add the exception handlers to the app (called from create_app)."""
    app.add_exception_handler(AppError, app_error_handler)
