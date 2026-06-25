import uuid
from collections.abc import Sequence

from sqlalchemy import Row, func, select

from app.db.models.product import Product
from app.db.models.product_shop import ProductShop
from app.db.models.user_product import UserProduct
from app.db.repositories.base import BaseRepository
from app.db.repositories.price_repo import latest_price_subq, utc_today_start


class ProductRepo(BaseRepository):
    """Доступ к таблице products и агрегатам цен по товару."""

    async def list_watchlist_with_prices(self, user_id: uuid.UUID) -> Sequence[Row]:
        """Товары из watchlist пользователя с min/max ценой и числом магазинов.

        Колонки: (id, title, category, price_min, price_max, shops_count).
        Диапазон цен — по сегодняшним записям (ТЗ: «диапазон цен на сегодня»).
        """
        latest = latest_price_subq(utc_today_start())
        q = (
            select(
                Product.id,
                Product.title,
                Product.category,
                func.min(latest.c.price_usd).label("price_min"),
                func.max(latest.c.price_usd).label("price_max"),
                func.count(ProductShop.id).label("shops_count"),
            )
            .join(UserProduct, UserProduct.product_id == Product.id)
            .join(ProductShop, ProductShop.product_id == Product.id)
            .outerjoin(latest, latest.c.product_shop_id == ProductShop.id)
            .where(UserProduct.user_id == user_id)
            .group_by(Product.id, Product.title, Product.category)
        )
        return (await self.db.execute(q)).all()

    async def list_watchlist_details(self, user_id: uuid.UUID) -> Sequence[Row]:
        """Карточки всех товаров watchlist пользователя одним запросом.

        Колонки: (id, title, description, category, price_min, price_max,
        shops_count). Диапазон цен — по сегодняшним записям. Используется вместо
        N запросов get_detail на каждый товар.
        """
        latest = latest_price_subq(utc_today_start())
        q = (
            select(
                Product.id,
                Product.title,
                Product.description,
                Product.category,
                func.min(latest.c.price_usd).label("price_min"),
                func.max(latest.c.price_usd).label("price_max"),
                func.count(ProductShop.id).label("shops_count"),
            )
            .join(UserProduct, UserProduct.product_id == Product.id)
            .join(ProductShop, ProductShop.product_id == Product.id)
            .outerjoin(latest, latest.c.product_shop_id == ProductShop.id)
            .where(UserProduct.user_id == user_id)
            .group_by(Product.id)
        )
        return (await self.db.execute(q)).all()

    async def get_detail(self, product_id: uuid.UUID) -> Row | None:
        """Карточка товара с агрегатами цен или None, если товара нет.

        Диапазон цен — по сегодняшним записям (ТЗ: «диапазон цен от и до»).
        """
        latest = latest_price_subq(utc_today_start())
        q = (
            select(
                Product.id,
                Product.title,
                Product.description,
                Product.category,
                func.min(latest.c.price_usd).label("price_min"),
                func.max(latest.c.price_usd).label("price_max"),
                func.count(ProductShop.id).label("shops_count"),
            )
            .join(ProductShop, ProductShop.product_id == Product.id)
            .outerjoin(latest, latest.c.product_shop_id == ProductShop.id)
            .where(Product.id == product_id)
            .group_by(Product.id)
        )
        return (await self.db.execute(q)).one_or_none()

    async def exists(self, product_id: uuid.UUID) -> bool:
        found = await self.db.scalar(
            select(Product.id).where(Product.id == product_id)
        )
        return found is not None
