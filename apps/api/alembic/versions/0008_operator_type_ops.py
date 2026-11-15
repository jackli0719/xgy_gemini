"""operator_type 枚举补一个取值 PLATFORM_OPS

Revision ID: 0008_operator_type_ops
Revises: 0007_provider_status
Create Date: 2026-11-15

背景：平台侧要管目录（品类 / 服务项，含改价）——PLAT-02。改价必须写
audit_log（R3：价格变更要能追溯到人），而 audit_log.operator_type 用的是
operator_type 枚举。这个枚举里原来没有 PLATFORM_OPS，只有 PLATFORM_ADMIN。

用 PLATFORM_ADMIN 顶替会丢信息：R3「非授权角色可触发金额变更」要靠
operator_type 区分是谁改的价，「平台管理员」和「平台运营」在审计上是
两拨人。这与 0006 给 operator_type 加 PLATFORM_FINANCE 是同一件事
（那时是财务确认结算要留痕），做法也照抄那条迁移。

注意事项：

- **必须用 AUTOCOMMIT 执行**：``ALTER TYPE ... ADD VALUE`` 会给这个枚举类型
  加锁，而 ``audit_log.operator_type`` / ``order_status_log.operator_type``
  两列都在用它——锁不放开，这两张表的写入就被阻塞。
  在普通事务里执行，锁会一直持到事务提交（也就是整条迁移链跑完），
  部署窗口里正好是业务写入最密集的时候。
  放进 ``autocommit_block()``：这条语句自己就是一个事务，
  加完值立刻提交、锁立刻放开，只持瞬时锁。
- **应用代码开始写 PLATFORM_OPS 之前，0008 必须已经执行**。
  枚举里没有这个取值时，往 operator_type 列写它会直接报错：
  ``invalid input value for enum operator_type: "PLATFORM_OPS"``。
  所以部署顺序是：先跑迁移，再上新代码。
- 用 ``IF NOT EXISTS``：枚举取值加上去就下不来了，downgrade 只能空转，
  于是「downgrade 到 0007 再 upgrade 回 head」这条路径会重复加同一个值。
  加上 IF NOT EXISTS，这条路径才是幂等的。
- downgrade 是空操作：PostgreSQL 不支持删除枚举取值。
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0008_operator_type_ops"
down_revision: str | None = "0007_provider_status"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # AUTOCOMMIT 隔离级别执行：加值立即提交，只持瞬时锁，
    # 不阻塞 audit_log / order_status_log 的写入。
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE operator_type ADD VALUE IF NOT EXISTS 'PLATFORM_OPS'"
        )


def downgrade() -> None:
    """空操作：PostgreSQL 的枚举取值加上去就删不掉了。

    留着这个值不影响任何逻辑——多一个取值不会让既有代码跑错，
    而强行重建类型会动到 audit_log / order_status_log 两张表的列。
    """
