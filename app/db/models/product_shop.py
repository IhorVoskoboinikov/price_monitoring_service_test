import uuid

from sqlalchemy import ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base


class ProductShop(Base):
    __tablename__ = "product_shops"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id")
    )
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"))
    external_id: Mapped[str] = mapped_column(String(100))

    __table_args__ = (
        UniqueConstraint("product_id", "shop_id"),
        Index("ix_product_shop_product_id", "product_id"),
    )
