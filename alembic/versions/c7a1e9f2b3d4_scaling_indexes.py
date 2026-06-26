"""scaling indexes for large catalog / price history

Adds/refines indexes for a growing DB (millions of products, years of history):
  • product_shops(shop_id)         — the fetcher reads links by shop
  • price_alerts(user_id, created_at DESC) — the user's alert list
  • price_alerts(product_id) WHERE is_active — partial index of active alerts
  • price_history(product_shop_id, recorded_at DESC) INCLUDE (price_usd)
       — covering index for the "last price" and history (index-only scan);
         replaces the old ix_price_history_lookup (does not add extra indexes on
         a write-hot table)

Note for production: on big tables, indexes should be built with
`CREATE INDEX CONCURRENTLY` (no lock). For the partitioned price_history you
cannot use CONCURRENTLY on the parent directly — the index is built on each
partition, then ATTACHed to the parent. Here we use a plain create_index
(fine for a fresh/small DB).

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
    # #1 — fetcher: list_product_shops(shop_id)
    op.create_index("ix_product_shop_shop_id", "product_shops", ["shop_id"])

    # #2 — user's alert list: WHERE user_id ORDER BY created_at DESC
    op.create_index(
        "ix_price_alert_user_created",
        "price_alerts",
        ["user_id", sa.text("created_at DESC")],
    )

    # #4 — partial index of active alerts instead of the full (is_active, product_id)
    op.drop_index("ix_price_alert_active_product", table_name="price_alerts")
    op.create_index(
        "ix_price_alert_active",
        "price_alerts",
        ["product_id"],
        postgresql_where=sa.text("is_active"),
    )

    # #3 — covering price_history index (DESC + INCLUDE), replaces the old one
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
