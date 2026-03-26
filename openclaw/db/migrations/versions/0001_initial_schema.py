"""Initial schema

Revision ID: 0001
Revises:
Create Date: 2026-03-26
"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "categories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False, unique=True),
        sa.Column("wb_subject_id", sa.Integer(), nullable=True),
        sa.Column("parent_id", sa.Integer(), sa.ForeignKey("categories.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_categories_name", "categories", ["name"])

    op.create_table(
        "products",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("wb_sku", sa.BigInteger(), nullable=True),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("brand", sa.String(200), nullable=True),
        sa.Column("seller", sa.String(200), nullable=True),
        sa.Column("category_id", sa.Integer(), sa.ForeignKey("categories.id"), nullable=True),
        sa.Column(
            "status",
            sa.Enum("active", "archived", "out_of_stock", name="productstatus"),
            server_default="active",
        ),
        sa.Column("price_rub", sa.Float(), nullable=True),
        sa.Column("price_sale_rub", sa.Float(), nullable=True),
        sa.Column("discount_pct", sa.Float(), nullable=True),
        sa.Column("sales_30d", sa.Integer(), nullable=True),
        sa.Column("revenue_30d_rub", sa.Float(), nullable=True),
        sa.Column("rating", sa.Float(), nullable=True),
        sa.Column("reviews_count", sa.Integer(), nullable=True),
        sa.Column("in_stock", sa.Boolean(), server_default=sa.true()),
        sa.Column("competitors_count", sa.Integer(), nullable=True),
        sa.Column("unit_cost_rub", sa.Float(), nullable=True),
        sa.Column("gross_profit_rub", sa.Float(), nullable=True),
        sa.Column("margin_pct", sa.Float(), nullable=True),
        sa.Column("roi_pct", sa.Float(), nullable=True),
        sa.Column("ai_score", sa.Float(), nullable=True),
        sa.Column("ai_verdict", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index("ix_products_name", "products", ["name"])
    op.create_index("ix_products_wb_sku", "products", ["wb_sku"])

    op.create_table(
        "price_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="CASCADE")),
        sa.Column("price_rub", sa.Float(), nullable=False),
        sa.Column("sales_count", sa.Integer(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_price_history_recorded_at", "price_history", ["recorded_at"])

    op.create_table(
        "supplier_offers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="CASCADE")),
        sa.Column("supplier_name", sa.String(300), nullable=False),
        sa.Column("supplier_url", sa.String(1000), nullable=True),
        sa.Column("price_cny", sa.Float(), nullable=True),
        sa.Column("price_rub", sa.Float(), nullable=True),
        sa.Column("min_order_qty", sa.Integer(), nullable=True),
        sa.Column("delivery_days", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )

    op.create_table(
        "telegram_users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tg_id", sa.BigInteger(), nullable=False, unique=True),
        sa.Column("username", sa.String(100), nullable=True),
        sa.Column("full_name", sa.String(300), nullable=True),
        sa.Column("wb_commission_pct", sa.Float(), server_default="15.0"),
        sa.Column("logistics_rub", sa.Float(), server_default="150.0"),
        sa.Column("storage_rate", sa.Float(), server_default="0.15"),
        sa.Column("return_rate", sa.Float(), server_default="0.10"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_telegram_users_tg_id", "telegram_users", ["tg_id"])

    op.create_table(
        "user_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("telegram_users.id", ondelete="CASCADE")
        ),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("response_summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )

    op.create_table(
        "scraper_tasks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_type", sa.String(50), nullable=False),
        sa.Column("target", sa.String(500), nullable=False),
        sa.Column(
            "status",
            sa.Enum("pending", "running", "done", "failed", name="taskstatus"),
            server_default="pending",
        ),
        sa.Column("products_found", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("scraper_tasks")
    op.drop_table("user_requests")
    op.drop_table("telegram_users")
    op.drop_table("supplier_offers")
    op.drop_table("price_history")
    op.drop_table("products")
    op.drop_table("categories")
