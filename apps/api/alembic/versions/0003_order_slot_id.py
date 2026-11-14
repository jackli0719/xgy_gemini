"""给 order 表补上 slot_id（预约时段）

Revision ID: 0003_order_slot_id
Revises: 0002_schedule_slot
Create Date: 2026-11-14

背景：T-07a 的初始迁移漏掉了 order.slot_id。订单必须绑定到具体的一格时段，
否则客服、退款、改约都无从定位用户订的是哪一格——而 (item_id, date, start_time)
无法唯一定位（同一服务项一天有多格）。

slot_id 是 NOT NULL 的，但加列前必须先确认 order 表为空：
非空时直接加 NOT NULL 列会失败，且无法在不丢数据的前提下自动回填。
因此这里显式检查——有数据就报错要求人工处理（先加可空列 → 回填 → 再改 NOT NULL），
绝不静默加默认值。
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_order_slot_id"
down_revision: str | None = "0002_schedule_slot"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    # "order" 是保留字，必须加引号
    has_rows = bind.execute(sa.text('SELECT EXISTS(SELECT 1 FROM "order")')).scalar()
    if has_rows:
        raise RuntimeError(
            "order 表已有数据，无法直接添加 NOT NULL 的 slot_id 列（会失败且无法自动回填）。"
            "请人工处理：先加可空列 -> 回填 slot_id -> 再改为 NOT NULL。"
        )

    op.add_column("order", sa.Column("slot_id", sa.BigInteger(), nullable=False))
    op.create_foreign_key(
        "fk_order_slot_id",
        "order",
        "schedule_slot",
        ["slot_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_order_slot_id", "order", ["slot_id"])


def downgrade() -> None:
    op.drop_index("ix_order_slot_id", table_name="order")
    op.drop_constraint("fk_order_slot_id", "order", type_="foreignkey")
    op.drop_column("order", "slot_id")
