"""补建 settlement / settlement_item（结算单与结算明细）

Revision ID: 0005_settlement
Revises: 0004_user_role_provider
Create Date: 2026-11-14

背景：订单「已完成」之后，钱要结算给服务商。T+1 定时任务把完工满一天的订单
聚成「待结算」结算单（app/services/settle.py），服务商确认后打款。
没有这两张表，结算链路无处落脚。

设计：

- settlement 按「服务商 + 结算周期」唯一（uq_settlement_provider_period）：
  同一服务商同一周期只允许一张结算单，避免重复生成。
- settlement_item 对 order_id 唯一（uq_settlement_item_order_id）：
  一笔订单只能被结算一次，这是幂等的兜底约束——
  不管哪条路径重复处理了同一笔订单，数据库都会挡住。
- 金额三件套都带 CHECK >= 0：负数金额一定是算错了。
- 外键全部 RESTRICT（结算单删除时明细 CASCADE）：
  订单和服务商都是钱的依据，不允许被物理删除。

注意：枚举类型由本迁移显式创建，表定义中一律 create_type=False，
避免重复 CREATE TYPE（模型侧首次引用用 create_type=True，
迁移侧用 False——两边分工不同，但最终 schema 必须一致）。
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_settlement"
down_revision: str | None = "0004_user_role_provider"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# 枚举取值。顺序不影响语义，但保持与 app/models/enums.py 的 SettlementStatus 一致。
SETTLEMENT_STATUS = (
    "PENDING",
    "CONFIRMED",
)

# 枚举类型由本迁移显式创建，表定义中一律 create_type=False，避免重复 CREATE TYPE
settlement_status = postgresql.ENUM(
    *SETTLEMENT_STATUS, name="settlement_status", create_type=False
)


def upgrade() -> None:
    op.execute(
        "CREATE TYPE settlement_status AS ENUM ({})".format(
            ", ".join("'{}'".format(v) for v in SETTLEMENT_STATUS)
        )
    )

    op.create_table(
        "settlement",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("provider_id", sa.BigInteger(), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("total_amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column(
            "commission_amount", sa.Numeric(precision=12, scale=2), nullable=False
        ),
        sa.Column("net_amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column(
            "status",
            settlement_status,
            nullable=False,
            server_default=sa.text("'PENDING'"),
        ),
        sa.Column("confirmed_by", sa.BigInteger(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.UniqueConstraint(
            "provider_id",
            "period_start",
            "period_end",
            name="uq_settlement_provider_period",
        ),
        sa.CheckConstraint("total_amount >= 0", name="ck_settlement_total_amount"),
        sa.CheckConstraint(
            "commission_amount >= 0", name="ck_settlement_commission_amount"
        ),
        sa.CheckConstraint("net_amount >= 0", name="ck_settlement_net_amount"),
        sa.CheckConstraint(
            "period_start <= period_end", name="ck_settlement_period_range"
        ),
    )
    op.create_index(
        "ix_settlement_provider_status", "settlement", ["provider_id", "status"]
    )

    op.create_table(
        "settlement_item",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("settlement_id", sa.BigInteger(), nullable=False),
        sa.Column("order_id", sa.BigInteger(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["settlement_id"],
            ["settlement.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["order.id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("order_id", name="uq_settlement_item_order_id"),
    )
    op.create_index(
        "ix_settlement_item_settlement_id", "settlement_item", ["settlement_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_settlement_item_settlement_id", table_name="settlement_item")
    op.drop_table("settlement_item")

    op.drop_index("ix_settlement_provider_status", table_name="settlement")
    op.drop_table("settlement")

    op.execute("DROP TYPE IF EXISTS settlement_status")
