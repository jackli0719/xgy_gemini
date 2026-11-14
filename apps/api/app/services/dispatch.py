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
   改写的字段。

状态变更必须留痕（R4）：每次真的发生状态变更，同一事务内写一条 order_status_log。

入参边界：只有 order_id 与 master_id。金额、状态、provider_id 全部由服务端决定。
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
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
        order = (
            await session.execute(select(Order).where(Order.id == order_id))
        ).scalar_one_or_none()
        if order is None:
            raise OrderNotFoundError(_ORDER_NOT_FOUND_DETAIL.format(order_id=order_id))

        # 归属校验放在状态校验之前。
        #
        # 顺序很重要：别家的订单无论处于什么状态，都只能得到 404。
        # 如果先查状态，别家就能通过「409 vs 404」的差异反推订单存不存在、
        # 甚至处于哪个状态。
        if order.provider_id is not None and order.provider_id != provider_id:
            # 与「不存在」同一个异常、同一句话
            raise OrderNotFoundError(
                _ORDER_NOT_FOUND_DETAIL.format(order_id=order_id)
            )

        # 状态校验：只有「待派单」能被派
        if order.status != OrderStatus.PENDING_DISPATCH:
            raise InvalidOrderStateError(
                "订单当前状态不能派单：order_id={}, status={}".format(
                    order_id, getattr(order.status, "value", order.status)
                )
            )

        # provider_id 不可变：已经写过归属的订单不能再派。
        # 走到这里说明 order.provider_id 要么是空的，要么等于 provider_id
        # （别家的已被上面的归属校验挡掉）。
        if order.provider_id is not None:
            raise InvalidOrderStateError(
                "订单已派单，不能重复派单：order_id={}".format(order_id)
            )

        # 师傅必须存在且属于本服务商。
        # 「不存在」与「属于别家」共用同一个异常、同一句话。
        master = (
            await session.execute(select(Master).where(Master.id == master_id))
        ).scalar_one_or_none()
        if master is None or master.provider_id != provider_id:
            raise MasterNotFoundError(_MASTER_NOT_FOUND_DETAIL.format(master_id=master_id))

        # 状态必须经状态机流转（R4）。非法流转在这里抛 OrderTransitionError，
        # 此时还没改过任何字段，事务回滚后订单原样不动。
        assert_transition(order.status, OrderStatus.PENDING_ACCEPT)

        order.provider_id = provider_id
        order.master_id = master.id
        order.status = OrderStatus.PENDING_ACCEPT
        order.dispatched_at = datetime.now(timezone.utc)

        # 状态变更必须留痕（R4）
        session.add(
            OrderStatusLog(
                order_id=order.id,
                from_status=OrderStatus.PENDING_DISPATCH,
                to_status=OrderStatus.PENDING_ACCEPT,
                operator_type=operator_type,
                operator_id=current_user.user_id,
                reason=DISPATCH_REASON,
            )
        )
        await session.flush()

    return order


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
