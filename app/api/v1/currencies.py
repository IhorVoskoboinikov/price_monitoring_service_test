from fastapi import APIRouter

from app.api.deps import CurrencyServiceDep, CurrentUser
from app.schemas.currency import CurrenciesResponse, CurrencyRateItem

router = APIRouter(prefix="/currencies", tags=["currencies"])


@router.get("", response_model=CurrenciesResponse)
async def get_currencies(
    _: CurrentUser,
    service: CurrencyServiceDep,
) -> CurrenciesResponse:
    """Return today's exchange rates for all available currencies."""
    rates = await service.get_today_rates()
    return CurrenciesResponse(
        items=[CurrencyRateItem.model_validate(r) for r in rates]
    )
