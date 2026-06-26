import uuid

from fastapi import APIRouter

from app.api.deps import AlertServiceDep, CurrentUserId
from app.api.responses import NOT_FOUND
from app.schemas.alert import AlertCreate, AlertListResponse, AlertResponse

router = APIRouter(prefix="/me/alerts", tags=["me"])


@router.get("", response_model=AlertListResponse)
async def get_alerts(
    user_id: CurrentUserId,
    service: AlertServiceDep,
) -> AlertListResponse:
    items = await service.get_alerts(user_id)
    return AlertListResponse(items=items)


@router.post("", response_model=AlertResponse, status_code=201, responses=NOT_FOUND)
async def create_alert(
    body: AlertCreate,
    user_id: CurrentUserId,
    service: AlertServiceDep,
) -> AlertResponse:
    return await service.create_alert(user_id, body)


@router.delete("/{alert_id}", status_code=204, responses=NOT_FOUND)
async def delete_alert(
    alert_id: uuid.UUID,
    user_id: CurrentUserId,
    service: AlertServiceDep,
) -> None:
    await service.delete_alert(user_id, alert_id)
