"""The OpenAPI schema documents the error codes each endpoint can return.

These checks are pure (no DB/network): they read the generated schema from the
app object, so they run in the unit suite. They guard against the per-route
`responses=` blocks drifting away from what the endpoints actually raise.
"""

from app.main import app

SCHEMA = app.openapi()
PATHS = SCHEMA["paths"]


def _codes(path: str, method: str) -> set[str]:
    return set(PATHS[path][method]["responses"].keys())


def test_error_response_schema_is_published():
    assert "ErrorResponse" in SCHEMA["components"]["schemas"]


def test_protected_endpoints_document_401():
    # 401 is attached once per protected router, so every guarded route has it.
    assert "401" in _codes("/api/v1/catalog", "get")
    assert "401" in _codes("/api/v1/products", "get")
    assert "401" in _codes("/api/v1/currencies", "get")
    assert "401" in _codes("/api/v1/me/products", "get")
    assert "401" in _codes("/api/v1/me/alerts", "get")


def test_public_health_has_no_401():
    assert "401" not in _codes("/api/v1/health", "get")


def test_500_documented_on_every_endpoint():
    # the global Exception handler can answer with the 500 envelope anywhere,
    # so it is documented once for the whole API — including public routes.
    assert "500" in _codes("/api/v1/health", "get")
    assert "500" in _codes("/api/v1/catalog", "get")
    assert "500" in _codes("/api/v1/me/products", "post")


def test_not_found_documented_only_where_raised():
    assert "404" in _codes("/api/v1/products/{product_id}", "get")
    assert "404" in _codes("/api/v1/products/{product_id}/prices", "get")
    assert "404" in _codes("/api/v1/me/products", "post")
    assert "404" in _codes("/api/v1/me/products/{product_id}", "delete")
    assert "404" in _codes("/api/v1/me/alerts", "post")
    assert "404" in _codes("/api/v1/me/alerts/{alert_id}", "delete")


def test_conflict_documented_only_on_watchlist_add():
    assert "409" in _codes("/api/v1/me/products", "post")
    # other write endpoints never raise a conflict
    assert "409" not in _codes("/api/v1/me/alerts", "post")


def test_codes_not_documented_where_not_raised():
    # price-history returns an empty series instead of 404
    assert "404" not in _codes("/api/v1/products/{product_id}/price-history", "get")
    # plain product list never raises NotFound
    assert "404" not in _codes("/api/v1/products", "get")
