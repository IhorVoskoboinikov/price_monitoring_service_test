from fastapi import APIRouter

from app.api.responses import UNAUTHORIZED
from app.api.v1 import (
    alerts,
    catalog,
    currencies,
    health,
    products,
    user_products,
)

router = APIRouter(prefix="/v1")

# health is public; everything else requires a Bearer token → document 401 once
router.include_router(health.router)
router.include_router(catalog.router, responses=UNAUTHORIZED)
router.include_router(products.router, responses=UNAUTHORIZED)
router.include_router(currencies.router, responses=UNAUTHORIZED)
router.include_router(user_products.router, responses=UNAUTHORIZED)
router.include_router(alerts.router, responses=UNAUTHORIZED)
