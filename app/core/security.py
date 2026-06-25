from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pydantic import ValidationError

from app.core.config import settings
from app.schemas.auth import TokenPayload

_ALGORITHM = "HS256"

_http_bearer = HTTPBearer()


def verify_token(
    credentials: HTTPAuthorizationCredentials = Depends(_http_bearer),
) -> TokenPayload:
    """
    Validates the Bearer JWT and returns the typed payload.
    Raises 401 on a bad signature or a payload missing required claims.

    Token is static (no expiration) — generated once via scripts/generate_token.py.
    """
    try:
        raw = jwt.decode(
            credentials.credentials,
            settings.app_secret_key,
            algorithms=[_ALGORITHM],
        )
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        return TokenPayload.model_validate(raw)
    except ValidationError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token payload is invalid",
            headers={"WWW-Authenticate": "Bearer"},
        )
