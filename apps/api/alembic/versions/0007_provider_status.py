"""provider_status 枚举补 PENDING / FROZEN，并把列默认值改成 PENDING

Revision ID: 0007_provider_status
Revises: 0006_operator_type_finance
Create Date: 2026-11-15

背景：平台侧要管服务商的入驻与冻结（PLAT-01），状态机是
``PENDING -> ACTIVE``（审核通过）/ ``ACTIVE -> FROZEN``（冻结）/
``FROZEN -> ACTIVE``（解冻）。而 0001 建出来的 provider_status 只有
``ACTIVE / SUSPENDED / CLOSED``：没有「待审核」，也没有「冻结」。

为什么不拿 SUSPENDED / CLOSED 顶替：

- SUSPENDED（停用）与 FROZEN（冻结）语义不同——冻结是「临时封禁，
  还能解冻」，停用是「不做了」。用同一个值表达两件事，以后没法区分
  「解冻」与「恢复营业」，审计日志里的 old/new 也读不出真实流程。
- PENDING（待审核）没有任何现成取值能顶：ACTIVE 是「已放行」，
  拿它当「待审核」等于默认放行，审核这一步就没了。

所以正经加两个取值（ADD VALUE），跟 0006 给 operator_type 加
PLATFORM_FINANCE 是同一套做法。

顺手改列默认值：``service_provider.status`` 原来默认 ACTIVE，
新建的服务商应该先是「待审核」。模型侧同步改了（见
app/models/provider.py），两条建库路径必须一致。

注意事项：

- **ADD VALUE 必须用 AUTOCOMMIT 执行**：``ALTER TYPE ... ADD VALUE`` 会给
  这个枚举类型加锁，而 ``service_provider.status`` 正用着它——锁不放开，
  这张表的写入就被阻塞。放进 ``autocommit_block()``：加完值立刻提交、
  锁立刻放开，只持瞬时锁（与 0006 同一理由）。
- **改列默认值必须放在 autocommit_block 外面**：PG 不允许「刚加上的枚举
  取值」在同一个事务里被使用（``unsafe use of new value``）。
  autocommit_block 退出时 alembic 会另起一个事务，那之后
  ``SET DEFAULT 'PENDING'`` 用的就是上一个事务里已经提交好的取值。
- **应用代码开始写 PENDING / FROZEN 之前，0007 必须已经执行**。
  枚举里没有这个取值时，往 status 列写它会直接报错：
  ``invalid input value for enum provider_status: "PENDING"``。
  部署顺序是：先跑迁移，再上新代码。
- 用 ``IF NOT EXISTS``：枚举取值加上去就下不来了，downgrade 只能空转，
  于是「downgrade 再 upgrade」这条路径会重复加同一个值。
- downgrade 只能把**列默认值**改回去（``'ACTIVE'``）；枚举取值删不掉。
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0007_provider_status"
down_revision: str | None = "0006_operator_type_finance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # AUTOCOMMIT 隔离级别执行：加值立即提交，只持瞬时锁，
    # 不阻塞 service_provider 的写入。
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE provider_status ADD VALUE IF NOT EXISTS 'PENDING'"
        )
        op.execute(
            "ALTER TYPE provider_status ADD VALUE IF NOT EXISTS 'FROZEN'"
        )

    # 这一句在 autocommit_block 外面：PG 不允许在同一个事务里使用
    # 「刚加上的枚举取值」，而 autocommit_block 退出时 alembic 已经
    # 另起了一个事务，这里用的 PENDING 是上一个事务里提交好的取值。
    op.execute(
        "ALTER TABLE service_provider ALTER COLUMN status SET DEFAULT 'PENDING'"
    )


def downgrade() -> None:
    """把列默认值改回去；枚举取值删不掉（PG 不支持）。

    ``PENDING`` / ``FROZEN`` 留在类型里不影响任何逻辑——多两个取值
    不会让既有代码跑错，而强行重建类型要动 service_provider.status 列
    （ALTER TYPE ... RENAME + ADD COLUMN + 回填 + 删旧列），代价远大于收益。
    """
    op.execute(
        "ALTER TABLE service_provider ALTER COLUMN status SET DEFAULT 'ACTIVE'"
    )
