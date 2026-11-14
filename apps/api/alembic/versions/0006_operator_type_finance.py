"""operator_type 枚举补一个取值 PLATFORM_FINANCE

Revision ID: 0006_operator_type_finance
Revises: 0005_settlement
Create Date: 2026-11-14

背景：财务确认结算（T-11b）要留痕两处——audit_log（金额 / 状态变更）与
order_status_log（订单状态流转）。两处的 operator_type 都是 operator_type
枚举，而这个枚举里原来没有 PLATFORM_FINANCE，只有 PLATFORM_ADMIN。

用 PLATFORM_ADMIN 顶替会丢信息：R3「非授权角色可触发金额变更」要靠
operator_type 区分是谁改的钱，「平台管理员」和「平台财务」在审计上是两拨人。
所以正经加一个取值。

为什么用 ADD VALUE 而不是重建类型：PostgreSQL 的枚举类型不能删取值，
重建类型要改所有引用它的列（ALTER TYPE ... RENAME + ADD COLUMN + 回填 + 删旧列），
代价远大于收益。ADD VALUE 是官方的增量做法。

注意事项：

- ``ADD VALUE`` 不能在同一个事务里使用新值，但**可以**在事务里执行
  （PG 12 起放宽了限制）。本迁移只加值、不写数据，安全。
- 用 ``IF NOT EXISTS``：枚举取值加上去就下不来了，downgrade 只能空转，
  于是「downgrade 到 0005 再 upgrade 回 head」这条路径会重复加同一个值。
  加上 IF NOT EXISTS，这条路径才是幂等的。
- downgrade 是空操作：PostgreSQL 不支持删除枚举取值。
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0006_operator_type_finance"
down_revision: str | None = "0005_settlement"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE operator_type ADD VALUE IF NOT EXISTS 'PLATFORM_FINANCE'"
    )


def downgrade() -> None:
    """空操作：PostgreSQL 的枚举取值加上去就删不掉了。

    留着这个值不影响任何逻辑——多一个取值不会让既有代码跑错，
    而强行重建类型会动到 audit_log / order_status_log 两张表的列。
    """
