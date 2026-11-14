"""下单链路初始表结构

Revision ID: 0001_initial
Revises:
Create Date: 2026-11-14

包含 8 张表：user / service_provider / master / service_category /
service_item / address / order / order_status_log，
以及 7 个 PostgreSQL 原生枚举类型。
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# ---------------------------------------------------------------- 枚举类型

USER_STATUS = ("ACTIVE", "DISABLED", "BANNED")
PROVIDER_STATUS = ("ACTIVE", "SUSPENDED", "CLOSED")
MASTER_STATUS = ("PENDING", "ACTIVE", "ON_LEAVE", "DISABLED")
CATALOG_STATUS = ("ACTIVE", "INACTIVE")
PAY_STATUS = ("UNPAID", "PAID", "REFUNDING", "REFUNDED")
ORDER_STATUS = (
    "PENDING_PAY",
    "PENDING_DISPATCH",
    "PENDING_ACCEPT",
    "ACCEPTED",
    "IN_SERVICE",
    "PENDING_CONFIRM",
    "COMPLETED",
    "PENDING_SETTLE",
    "SETTLED",
    "CANCELLED",
    "REFUNDING",
    "REFUNDED",
)
OPERATOR_TYPE = ("USER", "MASTER", "PROVIDER", "PLATFORM", "SYSTEM")

# 枚举类型由本迁移显式创建，表定义中一律 create_type=False，避免重复 CREATE TYPE
user_status = postgresql.ENUM(*USER_STATUS, name="user_status", create_type=False)
provider_status = postgresql.ENUM(*PROVIDER_STATUS, name="provider_status", create_type=False)
master_status = postgresql.ENUM(*MASTER_STATUS, name="master_status", create_type=False)
catalog_status = postgresql.ENUM(*CATALOG_STATUS, name="catalog_status", create_type=False)
pay_status = postgresql.ENUM(*PAY_STATUS, name="pay_status", create_type=False)
order_status = postgresql.ENUM(*ORDER_STATUS, name="order_status", create_type=False)
operator_type = postgresql.ENUM(*OPERATOR_TYPE, name="operator_type", create_type=False)


def upgrade() -> None:
    # 1. 枚举类型
    for name, values in (
        ("user_status", USER_STATUS),
        ("provider_status", PROVIDER_STATUS),
        ("master_status", MASTER_STATUS),
        ("catalog_status", CATALOG_STATUS),
        ("pay_status", PAY_STATUS),
        ("order_status", ORDER_STATUS),
        ("operator_type", OPERATOR_TYPE),
    ):
        op.execute(
            "CREATE TYPE {} AS ENUM ({})".format(
                name, ", ".join("'{}'".format(v) for v in values)
            )
        )

    # 2. user
    op.create_table(
        "user",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("phone", sa.String(length=32), nullable=False),
        sa.Column("nickname", sa.String(length=64), nullable=False, server_default=""),
        sa.Column(
            "status",
            user_status,
            nullable=False,
            server_default=sa.text("'ACTIVE'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("phone", name="uq_user_phone"),
    )

    # 3. service_provider
    op.create_table(
        "service_provider",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("contact_phone", sa.String(length=32), nullable=False),
        sa.Column(
            "status",
            provider_status,
            nullable=False,
            server_default=sa.text("'ACTIVE'"),
        ),
        sa.Column(
            "commission_rate",
            sa.Numeric(precision=5, scale=4),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "commission_rate >= 0 AND commission_rate <= 1",
            name="ck_service_provider_commission_rate",
        ),
    )

    # 4. master
    op.create_table(
        "master",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("provider_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("real_name", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            master_status,
            nullable=False,
            server_default=sa.text("'PENDING'"),
        ),
        sa.Column("rating", sa.Numeric(precision=2, scale=1), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["provider_id"],
            ["service_provider.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("user_id", name="uq_master_user_id"),
        sa.CheckConstraint(
            "rating IS NULL OR (rating >= 0 AND rating <= 5)",
            name="ck_master_rating",
        ),
    )
    op.create_index("ix_master_provider_id", "master", ["provider_id"])

    # 5. service_category
    op.create_table(
        "service_category",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("parent_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "status",
            catalog_status,
            nullable=False,
            server_default=sa.text("'ACTIVE'"),
        ),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["service_category.id"],
            ondelete="SET NULL",
        ),
    )
    op.create_index(
        "ix_service_category_parent_id", "service_category", ["parent_id"]
    )

    # 6. service_item
    op.create_table(
        "service_item",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("category_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("base_price", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("duration_min", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            catalog_status,
            nullable=False,
            server_default=sa.text("'ACTIVE'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["category_id"], ["service_category.id"], ondelete="RESTRICT"
        ),
        sa.CheckConstraint("base_price >= 0", name="ck_service_item_base_price"),
        sa.CheckConstraint("duration_min > 0", name="ck_service_item_duration_min"),
    )
    op.create_index("ix_service_item_category_id", "service_item", ["category_id"])

    # 7. address
    op.create_table(
        "address",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("contact", sa.String(length=64), nullable=False),
        sa.Column("phone", sa.String(length=32), nullable=False),
        sa.Column("region", sa.String(length=255), nullable=False),
        sa.Column("detail", sa.String(length=512), nullable=False),
        sa.Column(
            "is_default",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_address_user_id", "address", ["user_id"])

    # 8. order
    op.create_table(
        "order",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("order_no", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("provider_id", sa.BigInteger(), nullable=True),
        sa.Column("master_id", sa.BigInteger(), nullable=True),
        sa.Column("address_id", sa.BigInteger(), nullable=False),
        sa.Column("item_id", sa.BigInteger(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column(
            "status",
            order_status,
            nullable=False,
            server_default=sa.text("'PENDING_PAY'"),
        ),
        sa.Column(
            "pay_status",
            pay_status,
            nullable=False,
            server_default=sa.text("'UNPAID'"),
        ),
        sa.Column(
            "auto_confirmed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["provider_id"], ["service_provider.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["master_id"], ["master.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["address_id"], ["address.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["item_id"], ["service_item.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("order_no", name="uq_order_order_no"),
        sa.CheckConstraint("amount >= 0", name="ck_order_amount"),
    )
    op.create_index("ix_order_provider_status", "order", ["provider_id", "status"])
    op.create_index("ix_order_user_id", "order", ["user_id"])

    # 9. order_status_log
    op.create_table(
        "order_status_log",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("order_id", sa.BigInteger(), nullable=False),
        sa.Column("from_status", order_status, nullable=True),
        sa.Column("to_status", order_status, nullable=False),
        sa.Column("operator_type", operator_type, nullable=False),
        sa.Column("operator_id", sa.BigInteger(), nullable=True),
        sa.Column("reason", sa.String(length=512), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["order_id"], ["order.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_order_status_log_order_id", "order_status_log", ["order_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_order_status_log_order_id", table_name="order_status_log")
    op.drop_table("order_status_log")

    op.drop_index("ix_order_user_id", table_name="order")
    op.drop_index("ix_order_provider_status", table_name="order")
    op.drop_table("order")

    op.drop_index("ix_address_user_id", table_name="address")
    op.drop_table("address")

    op.drop_index("ix_service_item_category_id", table_name="service_item")
    op.drop_table("service_item")

    op.drop_index("ix_service_category_parent_id", table_name="service_category")
    op.drop_table("service_category")

    op.drop_index("ix_master_provider_id", table_name="master")
    op.drop_table("master")

    op.drop_table("service_provider")
    op.drop_table("user")

    for name in (
        "operator_type",
        "order_status",
        "pay_status",
        "catalog_status",
        "master_status",
        "provider_status",
        "user_status",
    ):
        op.execute("DROP TYPE IF EXISTS {}".format(name))
