"""派单 service。

服务商把「待派单」的订单派给本商师傅，订单状态从 PENDING_DISPATCH
推进到 PENDING_ACCEPT，等师傅接单。

五条硬约束（每一条都有测试盯着）：

1. **provider_id 只从 CurrentUser 取**，本函数的签名里根本没有 provider_id
   这个参数——不是「约定别传」，是「传不进来」。租户归属一旦能由客户端
   指定，隔离当场失效（R1）。请求体里带 provider_id 会被 schema 直接 422。
2. **归属校验不暴露存在性**：订单不属于本服务商、或师傅不属于本服务商，
   与「这个资源不存在」抛同一个异常、同一句话。调用方没法靠报错差异
   探测别家有没有这单、有没有这个人。
3. **归属通过后还要校验状态**：只有 PENDING_DISPATCH 能派。
4. **状态流转必须经状态机**（R4）：调 ``app.domain.order_state.assert_transition``，
   流转表是唯一事实来源，本模块不自己判断「能不能转」。
5. **order.provider_id 首次写入后不可变**：派单前为空（谁都能接），
   派单后指向承接的服务商，之后再派一律拒绝——服务商归属不是可以反复
   改写的字段。唯一的例外是「师傅拒单后退回本商」：归属服务商不变，
   只是清空承接师傅（master_id），订单可以重新派。
   注意这条不变式说的是 **归属不被改写**，不是「provider_id 只能是 NULL」：
   拒单后 provider_id 仍然是本商，master_id 已清空，两者的组合表示
   「这单在本商的待派单池里，当前没有承接人」。
6. **写订单必须用条件 UPDATE，不能读-改-写**：并发派单时读-改-写会丢更新
   （两个服务商都读到「还没派」，后提交的覆盖先提交的）。
   把「这单还没被派走」写进 WHERE 谓词，由数据库的行锁裁决，
   与 ``place_order._reserve_slot`` 扣库存同一套思路。

状态变更必须留痕（R4）：每次真的发生状态变更，同一事务内写一条 order_status_log。

入参边界：只有 order_id 与 master_id。金额、状态、provider_id 全部由服务端决定。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import NoReturn

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser
from app.domain.order_state import assert_transition
from app.models.enums import OperatorType, OrderStatus, UserRole
from app.models.order import Order, OrderStatusLog
from app.models.provider import Master
from app.services.errors import (
    DispatchForbiddenError,
    InvalidOrderStateError,
    MasterNotFoundError,
    OrderNotFoundError,
)

__all__ = ["dispatch_order"]

# 状态流转日志里记录的原因
DISPATCH_REASON = "服务商派单"

# 「不存在」与「不属于你」共用的消息。
#
# 消息里只回客户端自己给的 id，不含任何归属信息（属于谁、什么状态），
# 所以「别家的订单」和「根本不存在的订单」在响应里完全一样，
# 攻击者无法据此判断某个订单号是否真实存在（R1）。
_ORDER_NOT_FOUND_DETAIL = "订单不存在：order_id={order_id}"

# 同理，师傅的「不存在」与「属于别家」共用这一句。
_MASTER_NOT_FOUND_DETAIL = "师傅不存在：master_id={master_id}"

# 服务商侧角色 -> 状态流转日志里的操作方类型。
# 两套枚举的取值在这一段是对齐的（见 app/models/enums.py）。
_OPERATOR_TYPE_BY_ROLE: dict[UserRole, OperatorType] = {
    UserRole.PROVIDER_ADMIN: OperatorType.PROVIDER_ADMIN,
    UserRole.PROVIDER_STAFF: OperatorType.PROVIDER_STAFF,
}


async def dispatch_order(
    session: AsyncSession,
    *,
    order_id: int,
    master_id: int,
    current_user: CurrentUser,
) -> Order:
    """派单：把订单派给本商师傅，返回落库的订单。

    事务：查订单、查师傅、改状态、写日志在同一事务内，要么全成要么全不成。

    要求传入的 session 没有活动事务——本函数会自行管理事务生命周期。
    """
    provider_id = current_user.provider_id
    if provider_id is None:
        # 没有服务商归属就没有「本商」可言，直接拒绝，不碰订单
        raise DispatchForbiddenError("当前账号没有服务商归属，不能派单")

    operator_type = _operator_type_for(current_user.role)

    async with session.begin():
        # 师傅必须存在且属于本服务商。
        # 「不存在」与「属于别家」共用同一个异常、同一句话。
        #
        # 这一步放在写订单之前：师傅不是本商的就没资格派单，
        # 与订单当前是什么状态无关。
        master = (
            await session.execute(select(Master).where(Master.id == master_id))
        ).scalar_one_or_none()
        if master is None or master.provider_id != provider_id:
            raise MasterNotFoundError(
                _MASTER_NOT_FOUND_DETAIL.format(master_id=master_id)
            )

        now = datetime.now(timezone.utc)

        # 条件 UPDATE：把「这单还没被派走」写进 WHERE 谓词，
        # 由数据库的行锁保证并发下只有一个请求能改成功。
        #
        # 不能读-改-写。两个服务商同时派同一笔订单时，读-改-写会这样坏掉：
        #   T1 读到 provider_id IS NULL -> T2 也读到 provider_id IS NULL
        #   -> 两边各自改一遍 -> 后提交的那个把前一个的归属覆盖掉（丢更新）
        # 结果是订单归属和状态流转日志对不上（两条日志、两个归属）。
        #
        # 条件 UPDATE 把判定交给数据库：T2 的 UPDATE 会等 T1 的行锁，
        # 拿到锁后重新求值谓词，此时 provider_id 已经不为空，谓词不成立，
        # 影响 0 行 —— 天然 fail-safe。
        #
        # 与 place_order._reserve_slot 扣库存是同一套思路。
        result = await session.execute(
            update(Order)
            .where(
                Order.id == order_id,
                Order.status == OrderStatus.PENDING_DISPATCH,
                # 「归属不变式」有两种形态（provider_id 都不会被改成别家）：
                # - 还没派过单：provider_id IS NULL
                # - 师傅拒单后退回本商：provider_id 等于当前服务商，
                #   且 master_id 已清空（当前没有承接人，可以重新指派）。
                #   见 app/services/master_action.py 的「拒单只清 master_id」
                or_(
                    Order.provider_id.is_(None),
                    and_(
                        Order.provider_id == provider_id,
                        Order.master_id.is_(None),
                    ),
                ),
            )
            .values(
                provider_id=provider_id,
                master_id=master.id,
                status=OrderStatus.PENDING_ACCEPT,
                dispatched_at=now,
                # Core 的 UPDATE 不走 ORM 的 onupdate，得自己带上
                updated_at=func.now(),
            )
        )
        if result.rowcount != 1:
            await _raise_dispatch_conflict(
                session, order_id=order_id, provider_id=provider_id
            )

        # 防御性断言：条件 UPDATE 命中，说明这一行的状态确实是 PENDING_DISPATCH，
        # 到 PENDING_ACCEPT 的流转必然合法。状态机仍是唯一事实来源，
        # 这里只是不让「谓词写错了」这件事静默过去。
        assert_transition(OrderStatus.PENDING_DISPATCH, OrderStatus.PENDING_ACCEPT)

        # 状态变更必须留痕（R4）。同事务：条件 UPDATE 命中才写，
        # 命中的只有一方，所以留痕永远只有一条。
        session.add(
            OrderStatusLog(
                order_id=order_id,
                from_status=OrderStatus.PENDING_DISPATCH,
                to_status=OrderStatus.PENDING_ACCEPT,
                operator_type=operator_type,
                operator_id=current_user.user_id,
                reason=DISPATCH_REASON,
            )
        )
        await session.flush()

        # 回读这一行拿到落库后的订单（订单号、状态、师傅）。
        # 同一事务内、我们自己的 UPDATE 之后读到的一定是自己写进去的值。
        order = (
            await session.execute(select(Order).where(Order.id == order_id))
        ).scalar_one()

    return order


async def _raise_dispatch_conflict(
    session: AsyncSession, *, order_id: int, provider_id: int
) -> NoReturn:
    """条件 UPDATE 没命中时，回查那一行，区分失败原因。

    回查的是同一事务内的当前状态：并发场景下另一方可能刚刚提交，
    回查就能看到它写下的归属，于是能区分「这单已经被别家派走」（404）
    与「这单状态不对 / 本商已经派过」（409）。

    归属校验在状态校验之前：别家的订单无论处于什么状态，都只能得到 404。
    如果先查状态，别家就能通过「409 vs 404」的差异反推订单存不存在、
    甚至处于哪个状态。
    """
    row = (
        await session.execute(
            select(Order.provider_id, Order.status).where(Order.id == order_id)
        )
    ).one_or_none()
    if row is None:
        raise OrderNotFoundError(_ORDER_NOT_FOUND_DETAIL.format(order_id=order_id))

    order_provider_id, status = row
    if order_provider_id is not None and order_provider_id != provider_id:
        # 与「不存在」同一个异常、同一句话
        raise OrderNotFoundError(_ORDER_NOT_FOUND_DETAIL.format(order_id=order_id))

    if order_provider_id is not None:
        # 归属已经是本商的了：这单已经派过，不能重复派
        raise InvalidOrderStateError(
            "订单已派单，不能重复派单：order_id={}".format(order_id)
        )

    # 还没归属、但状态不对（例如还没支付）
    raise InvalidOrderStateError(
        "订单当前状态不能派单：order_id={}, status={}".format(
            order_id, getattr(status, "value", status)
        )
    )


def _operator_type_for(role: UserRole) -> OperatorType:
    """角色 -> 状态流转日志里的操作方类型。

    非服务商侧角色一律拒绝：派单是服务商侧动作，
    平台角色（PLATFORM_ADMIN 等）走的是平台自己的运营入口，
    不该混进服务商侧的派单流水里。
    """
    try:
        return _OPERATOR_TYPE_BY_ROLE[role]
    except KeyError:
        raise DispatchForbiddenError("当前角色不能派单") from None
