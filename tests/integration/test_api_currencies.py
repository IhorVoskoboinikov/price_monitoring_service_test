"""API tests for currencies: /currencies returns today's NBU rates."""


async def test_currencies_returns_seeded_rates(auth_client):
    resp = await auth_client.get("/api/v1/currencies")
    assert resp.status_code == 200
    items = resp.json()["items"]
    by_code = {i["currency_code"]: i for i in items}
    assert {"USD", "EUR", "GBP"} <= set(by_code)
    assert by_code["USD"]["rate_uah_per_unit"] == "44.86850000"
    assert by_code["EUR"]["rate_uah_per_unit"] == "50.88090000"


async def test_currencies_requires_auth(client):
    resp = await client.get("/api/v1/currencies")
    assert resp.status_code == 401
