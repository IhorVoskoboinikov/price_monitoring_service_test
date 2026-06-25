import uuid
from collections.abc import Sequence

from sqlalchemy import Row, delete, func, select, update

from app.db.models.price_alert import PriceAlert
from app.db.models.product import Product
from app.db.models.product_shop import ProductShop
from app.db.models.user import User
from app.db.repositories.base import BaseRepository
from app.db.repositories.price_repo import latest_price_subq


class AlertRepo(BaseRepository):
    """Доступ к таблице price_alerts."""

    async def list_by_user(self, user_id: uuid.UUID) -> Sequence[PriceAlert]:
        rows = (
            await self.db.execute(
                select(PriceAlert)
                .where(PriceAlert.user_id == user_id)
                .order_by(PriceAlert.created_at.desc())
            )
        ).scalars().all()
        return rows

    def add(self, alert: PriceAlert) -> None:
        self.db.add(alert)

    async def delete(self, alert_id: uuid.UUID, user_id: uuid.UUID) -> int:
        """Удаляет алерт пользователя. Возвращает число удалённых строк."""
        result = await self.db.execute(
            delete(PriceAlert).where(
                PriceAlert.id == alert_id,
                PriceAlert.user_id == user_id,
            )
        )
        return result.rowcount

    async def list_triggered(self) -> Sequence[Row]:
        """Активные алерты, у которых минимальная текущая цена товара (USD)
        опустилась до порога или ниже.

        Колонки: (id, email, product_title, threshold_price_usd, currency_code,
        min_price_usd).
        """
        latest = latest_price_subq()
        min_price = (
            select(
                ProductShop.product_id.label("product_id"),
                func.min(latest.c.price_usd).label("min_price"),
            )
            .join(latest, latest.c.product_shop_id == ProductShop.id)
            .group_by(ProductShop.product_id)
            .subquery()
        )
        q = (
            select(
                PriceAlert.id,
                User.email,
                Product.title.label("product_title"),
                PriceAlert.threshold_price_usd,
                PriceAlert.currency_code,
                min_price.c.min_price.label("min_price_usd"),
            )
            .join(User, User.id == PriceAlert.user_id)
            .join(Product, Product.id == PriceAlert.product_id)
            .join(min_price, min_price.c.product_id == PriceAlert.product_id)
            .where(
                PriceAlert.is_active.is_(True),
                min_price.c.min_price <= PriceAlert.threshold_price_usd,
            )
        )
        return (await self.db.execute(q)).all()

    async def deactivate(self, alert_id: uuid.UUID) -> None:
        """Помечает алерт сработавшим: is_active=False, triggered_at=now()."""
        await self.db.execute(
            update(PriceAlert)
            .where(PriceAlert.id == alert_id)
            .values(is_active=False, triggered_at=func.now())
        )
