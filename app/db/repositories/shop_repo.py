from collections.abc import Sequence

from sqlalchemy import select

from app.db.models.product_shop import ProductShop
from app.db.models.shop import Shop
from app.db.repositories.base import BaseRepository


class ShopRepo(BaseRepository):
    """Доступ к таблицам shops и product_shops."""

    async def list_active(self) -> Sequence[Shop]:
        rows = (
            await self.db.execute(select(Shop).where(Shop.is_active.is_(True)))
        ).scalars().all()
        return rows

    async def list_product_shops(self, shop_id: int) -> Sequence[ProductShop]:
        rows = (
            await self.db.execute(
                select(ProductShop).where(ProductShop.shop_id == shop_id)
            )
        ).scalars().all()
        return rows
