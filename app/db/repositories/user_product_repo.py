import uuid
from collections.abc import Sequence

from sqlalchemy import delete, select

from app.db.models.user_product import UserProduct
from app.db.repositories.base import BaseRepository


class UserProductRepo(BaseRepository):
    """Доступ к таблице user_products (watchlist)."""

    async def list_product_ids(self, user_id: uuid.UUID) -> Sequence[uuid.UUID]:
        rows = (
            await self.db.execute(
                select(UserProduct.product_id).where(UserProduct.user_id == user_id)
            )
        ).scalars().all()
        return rows

    async def exists(self, user_id: uuid.UUID, product_id: uuid.UUID) -> bool:
        found = await self.db.scalar(
            select(UserProduct.user_id).where(
                UserProduct.user_id == user_id,
                UserProduct.product_id == product_id,
            )
        )
        return found is not None

    def add(self, user_id: uuid.UUID, product_id: uuid.UUID) -> None:
        self.db.add(UserProduct(user_id=user_id, product_id=product_id))

    async def delete(self, user_id: uuid.UUID, product_id: uuid.UUID) -> int:
        result = await self.db.execute(
            delete(UserProduct).where(
                UserProduct.user_id == user_id,
                UserProduct.product_id == product_id,
            )
        )
        return result.rowcount
