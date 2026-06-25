"""Регистрация обработчиков исключений на FastAPI-приложении.

Доменные исключения сервисного слоя (app.core.exceptions) маппятся в HTTP-ответы
здесь — сервисы остаются независимыми от веб-слоя.
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.exceptions import AppError


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    """Доменное исключение → JSON-ответ с его HTTP-статусом."""
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


def register_exception_handlers(app: FastAPI) -> None:
    """Подключает обработчики исключений к приложению (вызывается из create_app)."""
    app.add_exception_handler(AppError, app_error_handler)
