"""mock 支付回调 service。

模拟第三方支付平台的异步回调：订单支付成功后，把订单从 PENDING_PAY
推进到 PENDING_DISPATCH（待派单）。

两条硬约束：

- **状态必须经状态机流转**（R4）。本模块不自己判断「能不能转」，
  一律调 ``app.domain.order_state.assert_transition``，
  状态流转表是唯一事实来源。
- **状态变更必须留痕**（R4）。每次真的发生状态变更，同一事务内写一条
  order_status_log；幂等分支不写。

入参边界：只有 order_no。金额绝不从入参取——金额是下单时的快照，
支付回调只确认「这笔订单已支付」，不重新定价。
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timezone import now_utc
from app.domain.order_state import assert_transition
from app.models.enums import OperatorType, OrderStatus, PayStatus
from app.models.order import Order, OrderStatusLog
from app.services.errors import InvalidOrderStateError, OrderNotFoundError

__all__ = ["mock_pay_success"]

# 状态流转日志里记录的来源
MOCK_PAY_REASON = "mock 支付成功"

# 幂等判定：订单已经推进到「待派单」及之后，且支付状态是「已支付」，
# 说明这笔支付的回调已经被处理过。
#
# 这里刻意写死集合，而不是从状态机推导：状态机是「能转哪些」的流转表，
# 不是「先后顺序」的排名表，从它推不出「更后」——PENDING_ACCEPT 还能退回
# PENDING_DISPATCH，用流转表做可达性闭包会把分支方向搞混。
#
# 不含 CANCELLED / REFUNDING / REFUNDED：那是取消与退款分支，
# 收到支付回调说明状态不对，应该报 409，而不是当成「已处理过」糊弄过去。
_ALREADY_PAID_STATUSES: frozenset[OrderStatus] = frozenset(
    {
        OrderStatus.PENDING_DISPATCH,
        OrderStatus.PENDING_ACCEPT,
        OrderStatus.ACCEPTED,
        OrderStatus.IN_SERVICE,
        OrderStatus.PENDING_CONFIRM,
        OrderStatus.COMPLETED,
        OrderStatus.PENDING_SETTLE,
        OrderStatus.SETTLED,
    }
)


async def mock_pay_success(session: AsyncSession, *, order_no: str) -> Order:
    """mock 支付成功：把订单推进到 PENDING_DISPATCH，返回落库的订单。

    幂等：重复回调同一笔订单时，第二次直接返回订单当前状态，
    不重复改 pay_status、不重复写 order_status_log。

    事务：查订单、改状态、写日志在同一事务内，要么全成要么全不成。

    要求传入的 session 没有活动事务——本函数会自行管理事务生命周期。
    """
    async with session.begin():
        order = (
            await session.execute(
                select(Order).where(Order.order_no == order_no)
            )
        ).scalar_one_or_none()
        if order is None:
            raise OrderNotFoundError("订单不存在：order_no={}".format(order_no))

        # 幂等：已经处理过了，原样返回，不写日志、不改 pay_status。
        #
        # 两个条件缺一不可：
        # - 状态已推进到「待派单」及之后：说明订单走过了支付这一步；
        # - pay_status 是「已支付」：说明这笔钱确实到账了。
        #
        # 只看状态会误判：订单跳过了支付环节（状态已是 ACCEPTED，
        # pay_status 还是 UNPAID）时，支付回调来了应该报 409（状态冲突），
        # 而不是当成「已处理过」返回 200 把冲突糊过去。
        if (
            order.status in _ALREADY_PAID_STATUSES
            and order.pay_status == PayStatus.PAID
        ):
            return order

        # 状态校验：只有「待支付」才能被支付回调推进
        if order.status != OrderStatus.PENDING_PAY:
            raise InvalidOrderStateError(
                "订单当前状态不能支付：order_no={}, status={}".format(
                    order_no, getattr(order.status, "value", order.status)
                )
            )

        # 状态必须经状态机流转（R4）。非法流转在这里抛 OrderTransitionError，
        # 此时还没改过任何字段，事务回滚后订单原样不动。
        assert_transition(order.status, OrderStatus.PENDING_DISPATCH)

        order.status = OrderStatus.PENDING_DISPATCH
        order.pay_status = PayStatus.PAID
        order.paid_at = now_utc()

        # 状态变更必须留痕（R4）。系统操作：operator_type=SYSTEM，operator_id=0
        session.add(
            OrderStatusLog(
                order_id=order.id,
                from_status=OrderStatus.PENDING_PAY,
                to_status=OrderStatus.PENDING_DISPATCH,
                operator_type=OperatorType.SYSTEM,
                operator_id=0,
                reason=MOCK_PAY_REASON,
            )
        )
        await session.flush()

    return order
