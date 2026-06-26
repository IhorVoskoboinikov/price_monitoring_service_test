import uuid

from app.core.exceptions import ConflictError, NotFoundError
from app.core.logger import get_logger
from app.db.repositories.product_repo import ProductRepo
from app.db.repositories.user_product_repo import UserProductRepo
from app.schemas.enums import Currency
from app.schemas.product import ProductDetail
from app.services.price_service import PriceService

logger = get_logger(__name__)


class UserProductService:
    """Manage the user's watchlist."""

    def __init__(
        self,
        user_products: UserProductRepo,
        products: ProductRepo,
        price_service: PriceService,
    ) -> None:
        self.user_products = user_products
        self.products = products
        self.price_service = price_service

    async def list_tracked(
        self, user_id: uuid.UUID, currency: Currency = Currency.USD
    ) -> list[ProductDetail]:
        # One aggregate query for the whole watchlist (no N+1 over products).
        return await self.price_service.get_watchlist_details(user_id, currency)

    async def add(self, user_id: uuid.UUID, product_id: uuid.UUID) -> None:
        if not await self.products.exists(product_id):
            raise NotFoundError("Product not found")
        if await self.user_products.exists(user_id, product_id):
            raise ConflictError("Product already in watchlist")
        self.user_products.add(user_id, product_id)
        logger.info(f"Watchlist add | user={user_id} product={product_id}")

    async def remove(self, user_id: uuid.UUID, product_id: uuid.UUID) -> None:
        deleted = await self.user_products.delete(user_id, product_id)
        if deleted == 0:
            raise NotFoundError("Product not in watchlist")
        logger.info(f"Watchlist remove | user={user_id} product={product_id}")
