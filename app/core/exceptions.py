"""Доменные исключения приложения.

Сервисный слой не зависит от HTTP/FastAPI — он бросает эти исключения, а API-слой
маппит их в ответы (см. обработчики в app/main.py). Так бизнес-логику можно
переиспользовать вне веб-контекста (Celery-задачи, CLI, тесты).
"""


class AppError(Exception):
    """Базовое доменное исключение. `status_code` использует API-слой для маппинга."""

    status_code: int = 400
    default_detail: str = "Application error"

    def __init__(self, detail: str | None = None) -> None:
        self.detail = detail or self.default_detail
        super().__init__(self.detail)


class NotFoundError(AppError):
    """Запрашиваемый ресурс не найден."""

    status_code = 404
    default_detail = "Resource not found"


class ConflictError(AppError):
    """Конфликт состояния (например, дубликат)."""

    status_code = 409
    default_detail = "Conflict"
