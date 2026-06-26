"""
Generate a static Bearer JWT for API testing.

Standalone helper: it does not import the app, so you can run it with plain
`python` without setting all the app settings (DATABASE_URL, REDIS_URL, ...).
It only needs the JWT secret, taken from APP_SECRET_KEY (the same value the API
uses), read from the environment or from the .env file in the project root.

Usage (from the project root):
    python scripts/generate_token.py
    # or: uv run python scripts/generate_token.py

Output:
    Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...

Paste the token into Swagger UI (Authorize button) or use it in curl:
    curl -H "Authorization: Bearer <token>" http://localhost:8000/api/v1/products
"""

import os

from dotenv import load_dotenv
from jose import jwt

load_dotenv()  # pull APP_SECRET_KEY from .env (same secret the API uses)

_ALGORITHM = "HS256"

# Fixed demo user — seeded by app/tasks/seed.py on first startup
DEMO_USER_ID = "10000000-0000-0000-0000-000000000001"

if __name__ == "__main__":
    payload = {
        "sub": "admin",
        "role": "admin",
        "user_id": DEMO_USER_ID,
    }
    token = jwt.encode(payload, os.environ["APP_SECRET_KEY"], algorithm=_ALGORITHM)
    print(f"Bearer {token}")
