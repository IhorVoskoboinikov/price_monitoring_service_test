import uuid

from pydantic import BaseModel, ConfigDict


class TokenPayload(BaseModel):
    """Типизированная полезная нагрузка JWT.

    Токен статический (см. app/core/security.py). `user_id` обязателен —
    эндпоинты идентифицируют пользователя по нему; остальные клеймы опциональны.
    """

    user_id: uuid.UUID
    sub: str | None = None
    role: str | None = None

    model_config = ConfigDict(extra="ignore")
