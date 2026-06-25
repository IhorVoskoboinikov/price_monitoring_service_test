"""
Generate a static Bearer JWT for API testing.

Usage (from project root):
    uv run python scripts/generate_token.py

Output:
    Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...

Paste the token into Swagger UI (Authorize button) or use in curl:
    curl -H "Authorization: Bearer <token>" http://localhost:8000/api/v1/products
"""

from jose import jwt

from app.core.config import settings

_ALGORITHM = "HS256"

# Fixed demo user — seeded by app/tasks/seed.py on first startup
DEMO_USER_ID = "10000000-0000-0000-0000-000000000001"

payload = {
    "sub": "admin",
    "role": "admin",
    "user_id": DEMO_USER_ID,
}

token = jwt.encode(payload, settings.app_secret_key, algorithm=_ALGORITHM)
print(f"Bearer {token}")
