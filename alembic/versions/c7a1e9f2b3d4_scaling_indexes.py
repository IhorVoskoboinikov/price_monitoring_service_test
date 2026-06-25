"""scaling indexes for large catalog / price history

Добавляет/уточняет индексы под рост БД (миллионы товаров, годы истории):
  • product_shops(shop_id)         — фетчер берёт связи по магазину
  • price_alerts(user_id, created_at DESC) — список алертов пользователя
  • price_alerts(product_id) WHERE is_active — partial-индекс активных алертов
  • price_history(product_shop_id, recorded_at DESC) INCLUDE (price_usd)
       — покрывающий индекс под «последнюю цену» и историю (index-only scan),
         заменяет прежний ix_price_history_lookup (не плодит индексы на
         write-горячей таблице)

Замечание по проду: на больших таблицах индексы стоит создавать
`CREATE INDEX CONCURRENTLY` (без блокировки). Для партиционированной
price_history CONCURRENTLY на родителе напрямую нельзя — индекс создаётся
на каждой партиции, затем ATTACH к родителю. Здесь — обычный create_index
(достаточно для свежей/небольшой БД).

Revision ID: c7a1e9f2b3d4
Revises: 11f8cd6cb440
Create Date: 2026-06-25 18:45:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c7a1e9f2b3d4"
down_revision: str | None = "11f8cd6cb440"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # #1 — фетчер: list_product_shops(shop_id)
    op.create_index("ix_product_shop_shop_id", "product_shops", ["shop_id"])

    # #2 — список алертов пользователя: WHERE user_id ORDER BY created_at DESC
    op.create_index(
        "ix_price_alert_user_created",
        "price_alerts",
        ["user_id", sa.text("created_at DESC")],
    )

    # #4 — partial-индекс активных алертов вместо полного (is_active, product_id)
    op.drop_index("ix_price_alert_active_product", table_name="price_alerts")
    op.create_index(
        "ix_price_alert_active",
        "price_alerts",
        ["product_id"],
        postgresql_where=sa.text("is_active"),
    )

    # #3 — покрывающий индекс price_history (DESC + INCLUDE), заменяет прежний
    op.drop_index("ix_price_history_lookup", table_name="price_history")
    op.create_index(
        "ix_price_history_lookup",
        "price_history",
        ["product_shop_id", sa.text("recorded_at DESC")],
        postgresql_include=["price_usd"],
    )


def downgrade() -> None:
    op.drop_index("ix_price_history_lookup", table_name="price_history")
    op.create_index(
        "ix_price_history_lookup",
        "price_history",
        ["product_shop_id", "recorded_at"],
    )

    op.drop_index("ix_price_alert_active", table_name="price_alerts")
    op.create_index(
        "ix_price_alert_active_product",
        "price_alerts",
        ["is_active", "product_id"],
    )

    op.drop_index("ix_price_alert_user_created", table_name="price_alerts")

    op.drop_index("ix_product_shop_shop_id", table_name="product_shops")
