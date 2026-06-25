from fastapi import APIRouter

from app.api.v1 import alerts, currencies, health, products, user_products

router = APIRouter(prefix="/v1")

router.include_router(health.router)
router.include_router(products.router)
router.include_router(currencies.router)
router.include_router(user_products.router)
router.include_router(alerts.router)
