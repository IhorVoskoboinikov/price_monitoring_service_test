"""Application domain exceptions.

The service layer does not depend on HTTP/FastAPI: it raises these exceptions, and
the API layer maps them to responses (see the handlers in app/main.py). This way the
business logic can be reused outside the web context (Celery tasks, CLI, tests).
"""


class AppError(Exception):
    """Base domain exception. The API layer uses `status_code` for mapping."""

    status_code: int = 400
    default_detail: str = "Application error"

    def __init__(self, detail: str | None = None) -> None:
        self.detail = detail or self.default_detail
        super().__init__(self.detail)


class NotFoundError(AppError):
    """The requested resource was not found."""

    status_code = 404
    default_detail = "Resource not found"


class ConflictError(AppError):
    """State conflict (for example, a duplicate)."""

    status_code = 409
    default_detail = "Conflict"
