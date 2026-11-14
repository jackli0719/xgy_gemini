"""T+1 待结算生成 service。

订单「已完成」之后，钱还没到服务商账上。订单完成当天就出结算单太早——
客户可能还在投诉、工期可能有争议。所以规则是 **T+1**：完工满一天的订单
才进入结算。本 service 负责把这类订单聚成「待结算」结算单：

- 找出 ``status='COMPLETED'`` 且 ``completed_at < now - 1 天`` 的订单；
- 按服务商聚合（不强求按天：同一批订单的周期由它们的完工日期决定）；
- 佣金按 ``service_provider.commission_rate`` 算：
  ``commission = 合计 × 费率``，``net = 合计 - 佣金``（服务商实收）；
- 逐笔条件 UPDATE 把订单转成「待结算」，并写入结算单、明细、状态流转日志、审计日志。

三条硬约束：

1. **条件 UPDATE，禁止读-改-写**：
   ``WHERE id=? AND status='COMPLETED'``。
   判定交给数据库的行锁裁决——两个任务实例同时跑时，
   只有一方能认领订单，不会生成两张结算单（与 service_flow / auto_confirm 同一套思路）。
2. **rowcount == 0 就跳过**：这一笔在等锁期间被人改走了，不是错误，
   跳过、继续处理下一笔。
3. **同一事务**：结算单 + 明细 + 订单状态 + 状态流转日志 + 审计日志，
   要么全成、要么全不成——不会出现「订单进了待结算却没有结算单」的中间态。

**审计日志为什么写三条**：audit_log 的设计是「一行 = 一个字段的变更」
（field_name + old_value + new_value）。结算单上的金额三件套
（total_amount / commission_amount / net_amount）是三个独立的金额口径，
各自都可能被质疑（合计对不对、佣金对不对、实收对不对）。
挤成一行就得把三个数塞进一个字符串，查「这张单的佣金是多少」时还得
再解析一次——既不好查，也容易在解析时丢精度。所以三个字段各记一条，
查的时候一句 SQL 就够。

**不抛业务异常给调用方**：单个服务商那一组失败只记日志、继续下一组。
定时任务因为一个服务商的脏数据整批失败，比漏掉一个服务商更糟。

**逐个服务商一个事务**：一个服务商出问题不会把已经结算好的其他服务商一起回滚。
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.order_state import assert_transition
from app.models.audit_log import AuditLog
from app.models.enums import OperatorType, OrderStatus, SettlementStatus
from app.models.order import Order, OrderStatusLog
from app.models.provider import ServiceProvider
from app.models.settlement import Settlement, SettlementItem

__all__ = ["AUDIT_REASON", "SETTLE_REASON", "generate_pending_settlements"]

logger = logging.getLogger(__name__)

# T+1：完工满一天才进结算
SETTLE_DELAY_DAYS = 1

# 状态流转日志里留下的原因
SETTLE_REASON = "T+1 自动生成待结算"

# 审计日志里留下的原因
AUDIT_REASON = "T+1 结算单生成"

# 审计日志里被审计对象的类型
AUDIT_TARGET_TYPE = "settlement"

# 系统操作没有真人，operator_id 记 0
SYSTEM_OPERATOR_ID = 0

# 金额精度：两位小数，四舍五入
CENTS = Decimal("0.01")


async def generate_pending_settlements(
    session: AsyncSession,
    *,
    now: datetime | None = None,
) -> int:
    """把完工满一天的订单聚成待结算结算单，返回本次转成「待结算」的订单笔数。

    ``now`` 为 None 时取当前时间（传入的必须是带时区的时间，naive 视为 UTC）。
    传入的 session 不能有活动事务——本函数自己管理事务。

    **不抛业务异常**：单个服务商那一组失败只记日志，继续下一组。
    """
    current = _resolve_now(now)
    cutoff = current - timedelta(days=SETTLE_DELAY_DAYS)

    # 候选查询单独一个事务：查完就提交，把事务边界让给逐服务商的结算。
    async with session.begin():
        candidates = list(
            (
                await session.execute(
                    select(
                        Order.id,
                        Order.provider_id,
                        Order.amount,
                        Order.completed_at,
                    )
                    .where(
                        Order.status == OrderStatus.COMPLETED,
                        Order.completed_at < cutoff,
                        # 没派到服务商的订单无从结算（正常流程下不存在这种订单）
                        Order.provider_id.is_not(None),
                    )
                    # 按 id 排序：并发时多个实例以同样的顺序加锁，避免死锁
                    .order_by(Order.id)
                )
            )
            .all()
        )

    # 按服务商聚合：一个服务商一张结算单
    grouped: dict[int, list] = defaultdict(list)
    for row in candidates:
        grouped[row.provider_id].append(row)

    settled = 0
    for provider_id in sorted(grouped):
        try:
            settled += await _settle_provider(
                session,
                provider_id=provider_id,
                rows=grouped[provider_id],
                now=current,
            )
        except Exception:  # noqa: BLE001 - 一个服务商坏掉不能拖垮整批
            logger.exception(
                "生成待结算失败：provider_id=%s", provider_id
            )

    logger.info(
        "待结算生成完成：候选 %d 笔，转 %d 笔（服务商 %d 个）",
        len(candidates),
        settled,
        len(grouped),
    )
    return settled


async def _settle_provider(
    session: AsyncSession,
    *,
    provider_id: int,
    rows: list,
    now: datetime,
) -> int:
    """结算一个服务商的订单，返回实际转成「待结算」的笔数。

    结算单、明细、订单状态、状态流转日志、审计日志在**同一个事务**里完成。
    """
    async with session.begin():
        provider = await session.get(ServiceProvider, provider_id)
        if provider is None:
            # 订单的外键是 RESTRICT，正常不会出现；
            # 真出现了说明数据坏了，不能凭空造一张没有佣金率的结算单。
            logger.error(
                "服务商不存在，跳过结算：provider_id=%s", provider_id
            )
            return 0

        # 逐笔条件 UPDATE「认领」订单：只有还是「已完成」的才动得了。
        # 两个任务实例同时跑时，先拿到行锁的那一方才认领得到，
        # 另一方等锁期间谓词已不成立 → rowcount == 0 → 跳过。
        claimed = []
        for row in rows:
            result = await session.execute(
                update(Order)
                .where(
                    Order.id == row.id,
                    Order.status == OrderStatus.COMPLETED,
                )
                .values(
                    status=OrderStatus.PENDING_SETTLE,
                    # Core 的 UPDATE 不走 ORM 的 onupdate，得自己带上
                    updated_at=now,
                )
                .returning(Order.id)
            )
            if result.first() is not None:
                claimed.append(row)

        if not claimed:
            # 这一组全被别人认领了（比如另一个任务实例刚跑过）
            return 0

        # 状态流转仍走状态机（R4）：COMPLETED -> PENDING_SETTLE 必须合法
        assert_transition(OrderStatus.COMPLETED, OrderStatus.PENDING_SETTLE)

        total = sum((row.amount for row in claimed), Decimal("0")).quantize(
            CENTS, rounding=ROUND_HALF_UP
        )
        commission, net = _split_amounts(total, provider.commission_rate)

        period_start = min(row.completed_at.date() for row in claimed)
        period_end = max(row.completed_at.date() for row in claimed)

        settlement = Settlement(
            provider_id=provider_id,
            period_start=period_start,
            period_end=period_end,
            total_amount=total,
            commission_amount=commission,
            net_amount=net,
            status=SettlementStatus.PENDING,
        )
        session.add(settlement)
        # flush 一下拿自增主键，才能写明细
        await session.flush()

        # 审计日志：金额三件套各记一条（理由见模块 docstring）
        for field_name, value in (
            ("total_amount", total),
            ("commission_amount", commission),
            ("net_amount", net),
        ):
            session.add(
                AuditLog(
                    operator_type=OperatorType.SYSTEM,
                    operator_id=SYSTEM_OPERATOR_ID,
                    target_type=AUDIT_TARGET_TYPE,
                    target_id=settlement.id,
                    provider_id=provider_id,
                    field_name=field_name,
                    # 结算单是新建的，之前没有值 -> old_value 为空
                    old_value=None,
                    new_value=str(value),
                    reason=AUDIT_REASON,
                )
            )

        for row in claimed:
            session.add(
                SettlementItem(
                    settlement_id=settlement.id,
                    order_id=row.id,
                    amount=row.amount,
                )
            )
            session.add(
                OrderStatusLog(
                    order_id=row.id,
                    from_status=OrderStatus.COMPLETED,
                    to_status=OrderStatus.PENDING_SETTLE,
                    operator_type=OperatorType.SYSTEM,
                    operator_id=SYSTEM_OPERATOR_ID,
                    reason=SETTLE_REASON,
                )
            )

    return len(claimed)


def _split_amounts(
    total: Decimal, commission_rate: Decimal
) -> tuple[Decimal, Decimal]:
    """按佣金率拆出「平台佣金」与「服务商实收」。

    - 佣金 = 合计 × 费率（四舍五入到分）；
    - 实收 = 合计 - 佣金。

    口径写死在模型注释里（app/models/settlement.py），
    别的地方算佣金必须走这个函数，避免两套口径算出两个数。
    """
    rate = Decimal(commission_rate or 0)
    commission = (total * rate).quantize(CENTS, rounding=ROUND_HALF_UP)
    net = (total - commission).quantize(CENTS, rounding=ROUND_HALF_UP)
    return commission, net


def _resolve_now(now: datetime | None) -> datetime:
    """确定「现在」：没传就取当前时间；naive 时间按 UTC 理解。

    库里存的是带时区的时间（timestamptz），拿 naive 时间去比较会直接抛异常——
    与其抛异常，不如明确按 UTC 解释。
    """
    if now is None:
        return datetime.now(timezone.utc)
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now
