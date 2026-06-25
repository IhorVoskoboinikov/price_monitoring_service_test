from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from app.core.config import settings

_ALGORITHM = "HS256"

_http_bearer = HTTPBearer()


def verify_token(
    credentials: HTTPAuthorizationCredentials = Depends(_http_bearer),
) -> dict:
    """
    Validates the Bearer JWT from the Authorization header.
    Returns the decoded payload on success, raises 401 on any error.

    Token is static (no expiration) — generated once via scripts/generate_token.py.
    """
    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.app_secret_key,
            algorithms=[_ALGORITHM],
        )
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing token",
            headers={"WWW-Authenticate": "Bearer"},
        )
