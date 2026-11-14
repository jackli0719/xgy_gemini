"""补建 schedule_slot（预约时段库存表）

Revision ID: 0002_schedule_slot
Revises: 0001_initial
Create Date: 2026-11-14

背景：T-07a 的初始迁移漏建 schedule_slot。T-07b-2b 的下单 service 需要对
该表做条件 UPDATE（`SET used = used + :count WHERE used + :count <= capacity`）
来原子扣减库存，必须先有这张表。

说明：
- 时段是服务项维度的库存，不建 provider_id 列；
  服务商派单时再按 provider 过滤订单。
- `used <= capacity` 的 CHECK 是数据库层的超卖兜底；
  并发原子性由条件 UPDATE 的行锁保证。
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_schedule_slot"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "schedule_slot",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("item_id", sa.BigInteger(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.Column("used", sa.Integer(), nullable=False, server_default=sa.text("0")),
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
            ["item_id"],
            ["service_item.id"],
            ondelete="RESTRICT",
        ),
        # 同一服务项同一日期同一开始时间只有一条时段
        sa.UniqueConstraint(
            "item_id",
            "date",
            "start_time",
            name="uq_schedule_slot_item_date_start",
        ),
        sa.CheckConstraint("capacity > 0", name="ck_schedule_slot_capacity"),
        sa.CheckConstraint("used >= 0", name="ck_schedule_slot_used"),
        sa.CheckConstraint("used <= capacity", name="ck_schedule_slot_used_le_capacity"),
        sa.CheckConstraint("start_time < end_time", name="ck_schedule_slot_time_range"),
    )
    # 查询某服务项某天的可用时段
    op.create_index("ix_schedule_slot_item_date", "schedule_slot", ["item_id", "date"])


def downgrade() -> None:
    op.drop_index("ix_schedule_slot_item_date", table_name="schedule_slot")
    op.drop_table("schedule_slot")
