"""超时自动确认 service。

客户确认完成后订单就结束；但客户可能一直不点「确认」。这类订单停在
「待确认」状态太久，整条链路就卡在中间——服务商结不了算，师傅的工钱
挂着，客户的订单也一直亮着。本 service 把这类订单自动收尾：

- 找出停在「待确认」且**超时**（``updated_at`` 早于 ``now - threshold``）的订单；
- 逐笔转成「已完成」，标记 ``auto_confirmed=True``；
- 同样写订单状态流转日志（R4）：操作方是系统，不是任何人。

四条硬约束：

1. **条件 UPDATE，禁止读-改-写**：
   ``WHERE id=? AND status='PENDING_CONFIRM'``。
   判定交给数据库的行锁裁决——客服手动确认与自动确认撞车时，
   只有一方能改成功，不会写出两条日志（与 service_flow 同一套思路）。
2. **rowcount == 0 就跳过**：这一笔在等锁期间被人手动确认了
   （或状态变了），不是错误，直接跳过、继续处理下一笔。
3. **不抛业务异常给调用方**：单笔失败记日志、继续下一笔。
   定时任务因为一笔脏数据整批失败，比漏掉一笔更糟。
4. **状态流转仍走状态机**（R4）：``PENDING_CONFIRM -> COMPLETED``
   必须先过 ``assert_transition``。

**逐笔一个事务**：一笔失败不会把已经确认好的几笔一起回滚。

阈值小时数不硬编码：默认取配置 ``auto_confirm_threshold_hours``（默认 24 小时），
调用方也可以显式传参覆盖。
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.domain.order_state import assert_transition
from app.models.enums import OperatorType, OrderStatus
from app.models.order import Order, OrderStatusLog

__all__ = ["AUTO_CONFIRM_REASON", "auto_confirm_expired"]

logger = logging.getLogger(__name__)

# 自动确认在状态流转日志里留下的原因
AUTO_CONFIRM_REASON = "超时自动确认"

# 系统操作没有真人，operator_id 记 0
SYSTEM_OPERATOR_ID = 0

# 阈值默认值（配置项 auto_confirm_threshold_hours 的兜底）
DEFAULT_THRESHOLD_HOURS = 24


async def auto_confirm_expired(
    session: AsyncSession,
    *,
    threshold_hours: int | None = None,
) -> int:
    """把超时未确认的订单自动确认，返回本次确认的笔数。

    ``threshold_hours`` 为 None 时取配置项 ``auto_confirm_threshold_hours``
    （默认 24 小时）。传入的 session 不能有活动事务——本函数自己管理事务。

    **不抛业务异常**：单笔失败只记日志，继续处理下一笔。
    """
    hours = _resolve_threshold_hours(threshold_hours)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    # 候选查询单独一个事务：查完就提交，把事务边界让给逐笔处理。
    async with session.begin():
        candidate_ids = list(
            (
                await session.execute(
                    select(Order.id).where(
                        Order.status == OrderStatus.PENDING_CONFIRM,
                        Order.updated_at < cutoff,
                    )
                )
            )
            .scalars()
            .all()
        )

    confirmed = 0
    for order_id in candidate_ids:
        try:
            if await _confirm_one(session, order_id=order_id):
                confirmed += 1
        except Exception:  # noqa: BLE001 - 单笔失败不能拖垮整批
            # 记日志（含订单 id）后继续：定时任务整体失败比漏掉一笔更糟
            logger.exception("超时自动确认失败：order_id=%s", order_id)

    logger.info(
        "超时自动确认完成：候选 %d 笔，确认 %d 笔（阈值 %s 小时）",
        len(candidate_ids),
        confirmed,
        hours,
    )
    return confirmed


async def _confirm_one(session: AsyncSession, *, order_id: int) -> bool:
    """确认一笔订单；返回是否真的确认了。

    条件 UPDATE 没命中（``rowcount == 0``）说明这一笔在我们等待期间
    已经被别的路径确认了——不是错误，返回 False 跳过即可。
    """
    async with session.begin():
        now = datetime.now(timezone.utc)
        result = await session.execute(
            update(Order)
            .where(
                Order.id == order_id,
                # 目标状态：只有还停在「待确认」的订单才动得了
                Order.status == OrderStatus.PENDING_CONFIRM,
            )
            .values(
                status=OrderStatus.COMPLETED,
                # 标记这笔是系统自动确认的，与人工确认区分开
                auto_confirmed=True,
                # 自动确认同样要写完工时间：订单确实做完了
                completed_at=now,
                # Core 的 UPDATE 不走 ORM 的 onupdate，得自己带上
                updated_at=now,
            )
            .returning(Order.id)
        )
        row = result.first()
        if row is None:
            # 没命中：有人先确认了 / 状态已经变了。跳过，不报错。
            return False

        # 防御性断言：条件 UPDATE 命中说明状态确实是「待确认」，
        # 到「已完成」的流转必然合法。状态机仍是唯一事实来源。
        assert_transition(OrderStatus.PENDING_CONFIRM, OrderStatus.COMPLETED)

        session.add(
            OrderStatusLog(
                order_id=order_id,
                from_status=OrderStatus.PENDING_CONFIRM,
                to_status=OrderStatus.COMPLETED,
                operator_type=OperatorType.SYSTEM,
                operator_id=SYSTEM_OPERATOR_ID,
                reason=AUTO_CONFIRM_REASON,
            )
        )
    return True


def _resolve_threshold_hours(threshold_hours: int | None) -> int:
    """确定超时阈值小时数。

    不传就用配置项（默认 24 小时）。非正数直接报错：
    阈值配错会让「0 小时 = 全部订单立刻自动确认」，
    静默兜底会把还没完工的订单全部确认掉——宁可启动失败。
    """
    if threshold_hours is None:
        threshold_hours = settings.auto_confirm_threshold_hours
    if threshold_hours <= 0:
        raise ValueError(
            "threshold_hours 必须为正整数，当前 {}".format(threshold_hours)
        )
    return threshold_hours
