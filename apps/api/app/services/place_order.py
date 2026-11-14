"""下单 service。

一次下单 = 扣库存 + 创建订单 + 写状态流转日志，三者同一事务。

设计约束（来自 T-07b-2b-2 设计稿，两条硬伤）：
- 校验阶段只取标量、不持有 ORM 对象。校验结束要 `await session.rollback()`，
  这会让 session 内的持久化对象过期；async 下访问其属性会触发 lazy load，
  直接抛 MissingGreenlet / InvalidRequestError。
- 重试循环必须分类退出：只有 order_no 唯一约束冲突才重试；
  库存不足、时段消失、其他完整性冲突一律立即退出向上抛。

入参边界：只有 user_id / item_id / slot_id / address_id。
金额、订单号、状态、派单信息全部由服务端决定，绝不接受客户端传入。
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.order_no import generate_order_no
from app.domain.pricing import snapshot_amount
from app.domain.slot_rule import assert_reservable
from app.models.address import Address
from app.models.catalog import ServiceItem
from app.models.enums import CatalogStatus, OperatorType, OrderStatus, PayStatus
from app.models.order import Order, OrderStatusLog
from app.models.schedule_slot import ScheduleSlot
from app.services.errors import (
    AddressNotFoundError,
    ItemInactiveError,
    ItemNotFoundError,
    OrderNoConflictError,
    PlaceOrderError,
    SlotItemMismatchError,
    SlotNotFoundError,
    SlotNotInFutureError,
)

__all__ = ["place_order"]

# 订单号冲突时的最大尝试次数（首次 + 2 次重试）
MAX_ORDER_NO_ATTEMPTS = 3

# 下单固定占用 1 个名额
RESERVE_COUNT = 1

# PostgreSQL unique_violation 的 SQLSTATE
SQLSTATE_UNIQUE_VIOLATION = "23505"

# order_no 的唯一约束名，用于识别「订单号冲突」这一种可重试错误
ORDER_NO_CONSTRAINT = "uq_order_order_no"

# 兜底解析约束名：PostgreSQL 的错误消息形如
# duplicate key value violates unique constraint "uq_order_order_no"
_CONSTRAINT_PATTERN = re.compile(r'constraint "([^"]+)"')


async def place_order(
    session: AsyncSession,
    *,
    user_id: int,
    item_id: int,
    slot_id: int,
    address_id: int,
) -> Order:
    """创建一笔订单，返回落库的订单。

    事务结构：
    1. 事务外：前置校验（纯只读），得到金额快照；
    2. 事务内：条件 UPDATE 扣库存 -> insert order -> insert order_status_log。

    要求传入的 session 没有活动事务——本函数会自行管理事务生命周期。
    """
    amount = await _validate_place_order(
        session,
        user_id=user_id,
        item_id=item_id,
        slot_id=slot_id,
        address_id=address_id,
    )
    # 结束校验阶段 autobegin 出来的只读事务，
    # 否则下面的 session.begin() 会报 "a transaction is already begun"
    await session.rollback()

    for _attempt in range(MAX_ORDER_NO_ATTEMPTS):
        try:
            async with session.begin():
                # 订单号每轮重新生成：冲突后必须换号，不能用同一个号重试
                order_no = generate_order_no()
                await _reserve_slot(session, slot_id=slot_id)
                order = Order(
                    order_no=order_no,
                    user_id=user_id,
                    # 未派单：服务商与师傅都为空
                    provider_id=None,
                    master_id=None,
                    address_id=address_id,
                    item_id=item_id,
                    slot_id=slot_id,
                    amount=amount,
                    status=OrderStatus.PENDING_PAY,
                    pay_status=PayStatus.UNPAID,
                )
                session.add(order)
                await session.flush()
                # 建单即状态进入，必须留痕（R4）
                session.add(
                    OrderStatusLog(
                        order_id=order.id,
                        from_status=None,
                        to_status=OrderStatus.PENDING_PAY,
                        operator_type=OperatorType.USER,
                        operator_id=user_id,
                        reason="用户下单",
                    )
                )
                await session.flush()
            return order
        except IntegrityError as exc:
            if not _is_order_no_violation(exc):
                # 其他完整性冲突（外键、CHECK 等）不重试，直接转业务异常
                raise PlaceOrderError(
                    "下单时数据库完整性约束冲突：{}".format(exc)
                ) from exc
            # order_no 唯一冲突：事务已由 session.begin() 的上下文回滚，
            # 下一轮开新事务重试
            continue

    raise OrderNoConflictError(
        "订单号连续冲突，{} 次尝试均未成功".format(MAX_ORDER_NO_ATTEMPTS)
    )


async def _validate_place_order(
    session: AsyncSession,
    *,
    user_id: int,
    item_id: int,
    slot_id: int,
    address_id: int,
) -> Decimal:
    """事务外的前置校验，返回订单金额快照。

    这里刻意只 select 标量列、不 select ORM 实体：校验结束会 rollback，
    session 内的持久化对象随之过期，async 下访问其属性会触发 lazy load
    （MissingGreenlet / InvalidRequestError）。
    """
    # 地址必须属于当前用户。
    # 「不存在」与「不属于你」抛同一个异常，消息也不含归属信息，
    # 避免被用来探测他人资源是否存在（R5）
    address_hit = (
        await session.execute(
            select(Address.id).where(
                Address.id == address_id,
                Address.user_id == user_id,
            )
        )
    ).first()
    if address_hit is None:
        raise AddressNotFoundError("地址不存在：address_id={}".format(address_id))

    # 服务项必须存在且启用
    item_row = (
        await session.execute(
            select(ServiceItem.base_price, ServiceItem.status).where(
                ServiceItem.id == item_id
            )
        )
    ).one_or_none()
    if item_row is None:
        raise ItemNotFoundError("服务项不存在：item_id={}".format(item_id))
    base_price, item_status = item_row
    if item_status != CatalogStatus.ACTIVE:
        raise ItemInactiveError("服务项已停用：item_id={}".format(item_id))

    # 时段必须存在、属于该服务项、且在将来
    slot_row = (
        await session.execute(
            select(
                ScheduleSlot.id,
                ScheduleSlot.item_id,
                ScheduleSlot.date,
                ScheduleSlot.start_time,
                ScheduleSlot.capacity,
                ScheduleSlot.used,
            ).where(ScheduleSlot.id == slot_id)
        )
    ).one_or_none()
    if slot_row is None:
        raise SlotNotFoundError("预约时段不存在：slot_id={}".format(slot_id))
    found_slot_id, slot_item_id, slot_date, slot_start, capacity, used = slot_row
    if slot_item_id != item_id:
        raise SlotItemMismatchError(
            "时段不属于该服务项：slot_id={}, item_id={}".format(slot_id, item_id)
        )
    slot_start_at = datetime.combine(slot_date, slot_start, tzinfo=timezone.utc)
    if slot_start_at <= datetime.now(timezone.utc):
        raise SlotNotInFutureError(
            "时段不在将来：slot_id={}".format(slot_id)
        )

    # 金额只来自服务项基准价（服务端数据）；客户端传入的金额一律不接受
    return snapshot_amount(base_price)


async def _reserve_slot(session: AsyncSession, *, slot_id: int) -> None:
    """条件 UPDATE 扣库存。

    把「还有没有库存」写进 WHERE 谓词，由数据库的行锁保证并发下不超卖：
    两个并发请求抢最后一个名额时，先到的事务提交后 used == capacity，
    后到的事务等锁后重新求值谓词不成立，影响 0 行。
    绝不能「先 SELECT used 再 UPDATE used = used + 1」——那是读-改写竞态。
    """
    result = await session.execute(
        update(ScheduleSlot)
        .where(
            ScheduleSlot.id == slot_id,
            ScheduleSlot.used + RESERVE_COUNT <= ScheduleSlot.capacity,
        )
        .values(used=ScheduleSlot.used + RESERVE_COUNT, updated_at=func.now())
    )
    if result.rowcount == 1:
        return

    # 影响 0 行：同事务内重查，确认是库存不足还是时段已被删除
    row = (
        await session.execute(
            select(ScheduleSlot.capacity, ScheduleSlot.used).where(
                ScheduleSlot.id == slot_id
            )
        )
    ).one_or_none()
    if row is None:
        raise SlotNotFoundError("预约时段不存在：slot_id={}".format(slot_id))
    capacity, used = row
    # 库存规则以 domain/slot_rule 为唯一事实来源：
    # 这里只复用它的判定与异常，不在这里另写一套规则
    assert_reservable(capacity, used, RESERVE_COUNT)


def _is_order_no_violation(exc: IntegrityError) -> bool:
    """判断 IntegrityError 是否为 order_no 唯一约束冲突。

    只有 PostgreSQL unique_violation(23505) 且冲突的是 uq_order_order_no
    才值得重试；其他完整性错误重试没有意义。
    """
    sqlstate, constraint_name = _db_error_fields(exc)
    if sqlstate != SQLSTATE_UNIQUE_VIOLATION:
        return False
    if constraint_name is None:
        constraint_name = _constraint_from_message(str(exc))
    return constraint_name == ORDER_NO_CONSTRAINT


def _db_error_fields(exc: BaseException) -> tuple[str | None, str | None]:
    """沿异常链取出 (sqlstate, constraint_name)。

    SQLAlchemy 的 asyncpg 适配层会把驱动异常包一层：
    IntegrityError.orig 是方言层的包装（有 sqlstate，没有 constraint_name），
    原始 asyncpg 异常挂在 __cause__ / __context__ 上，两个字段都有。
    所以这里把整条链都走一遍。
    """
    sqlstate: str | None = None
    constraint_name: str | None = None
    visited: set[int] = set()
    queue: list[BaseException | None] = [exc]
    while queue:
        candidate = queue.pop(0)
        if candidate is None or id(candidate) in visited:
            continue
        visited.add(id(candidate))
        if sqlstate is None:
            sqlstate = getattr(candidate, "sqlstate", None)
        if constraint_name is None:
            constraint_name = getattr(candidate, "constraint_name", None)
        for attribute in ("__cause__", "__context__", "orig"):
            queue.append(getattr(candidate, attribute, None))
    return sqlstate, constraint_name


def _constraint_from_message(message: str) -> str | None:
    """从数据库错误消息里兜底解析约束名（驱动没给约束名时用）。"""
    match = _CONSTRAINT_PATTERN.search(message)
    return match.group(1) if match else None
