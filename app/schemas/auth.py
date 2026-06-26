import uuid

from pydantic import BaseModel, ConfigDict


class TokenPayload(BaseModel):
    """Typed JWT payload.

    The token is static (see app/core/security.py). `user_id` is required —
    endpoints identify the user by it; the other claims are optional.
    """

    user_id: uuid.UUID
    sub: str | None = None
    role: str | None = None

    model_config = ConfigDict(extra="ignore")
