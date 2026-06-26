from fastapi import APIRouter

from app.api import v1
from app.api.responses import INTERNAL_ERROR

router = APIRouter(prefix="/api")

# every route can fail with the same 500 envelope -> document it once for all
router.include_router(v1.router, responses=INTERNAL_ERROR)
