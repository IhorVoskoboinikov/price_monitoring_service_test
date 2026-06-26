"""Reusable OpenAPI `responses=` blocks so error codes show up in Swagger.

Doc-only metadata (does not change runtime behaviour). Attach them per route to
the codes that route can actually return — 500 is applied once for the whole API
in app/api/__init__.py, 401 once per protected router in app/api/v1/__init__.py,
404/409 are added on the specific routes that raise them.
"""

from app.schemas.error import ErrorResponse

INTERNAL_ERROR = {
    500: {"model": ErrorResponse, "description": "Internal server error"}
}
UNAUTHORIZED = {
    401: {"model": ErrorResponse, "description": "Missing or invalid token"}
}
NOT_FOUND = {
    404: {"model": ErrorResponse, "description": "Resource not found"}
}
CONFLICT = {
    409: {"model": ErrorResponse, "description": "Conflict (e.g. already exists)"}
}
