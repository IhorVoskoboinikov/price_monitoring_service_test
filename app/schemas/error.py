from pydantic import BaseModel


class ErrorResponse(BaseModel):
    """Standard error body returned by the API (matches the exception handlers)."""

    detail: str
