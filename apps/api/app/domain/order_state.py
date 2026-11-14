"""订单状态机（纯逻辑）。

职责边界：只做「某个状态能否流转到另一个状态」的判定，
不写数据库、不写日志、不取时间戳、不做任何 I/O。

状态取值直接复用 0001 迁移里定义的 order_status 枚举（app/models/enums.py），
本文件不重新定义字符串常量，避免与数据库枚举漂移。
"""
from __future__ import annotations

from app.models.enums import OrderStatus

__all__ = [
    "OrderTransitionError",
    "OrderStatus",
    "TERMINAL_STATUSES",
    "allowed_next_statuses",
    "assert_transition",
    "is_valid_transition",
]


class OrderTransitionError(Exception):
    """非法的订单状态流转。

    携带流转两端的状态，便于调用方记日志或返回错误详情。
    """

    def __init__(self, from_status: OrderStatus, to_status: OrderStatus) -> None:
        self.from_status = from_status
        self.to_status = to_status
        super().__init__(
            "订单状态不能从 {} 流转到 {}".format(
                getattr(from_status, "value", from_status),
                getattr(to_status, "value", to_status),
            )
        )


# 流转表：整个状态机唯一的数据源。
# 键为来源状态，值为可流转到的目标状态。
# 值用 tuple 而非 set/set 容器，是为了保留流转表的书写顺序，
# 使 allowed_next_statuses 的返回顺序稳定、可被断言。
# 表外的流转一律不合法（fail-closed），没有兜底放行分支。
_TRANSITIONS: dict[OrderStatus, tuple[OrderStatus, ...]] = {
    OrderStatus.PENDING_PAY: (
        OrderStatus.PENDING_DISPATCH,
        OrderStatus.CANCELLED,
    ),
    OrderStatus.PENDING_DISPATCH: (
        OrderStatus.PENDING_ACCEPT,
        OrderStatus.REFUNDING,
    ),
    OrderStatus.PENDING_ACCEPT: (
        OrderStatus.ACCEPTED,
        OrderStatus.PENDING_DISPATCH,
        OrderStatus.REFUNDING,
    ),
    OrderStatus.ACCEPTED: (
        OrderStatus.IN_SERVICE,
        OrderStatus.REFUNDING,
    ),
    OrderStatus.IN_SERVICE: (OrderStatus.PENDING_CONFIRM,),
    OrderStatus.PENDING_CONFIRM: (OrderStatus.COMPLETED,),
    OrderStatus.COMPLETED: (OrderStatus.PENDING_SETTLE,),
    OrderStatus.PENDING_SETTLE: (OrderStatus.SETTLED,),
    OrderStatus.REFUNDING: (OrderStatus.REFUNDED,),
    # 终态：无出边
    OrderStatus.CANCELLED: (),
    OrderStatus.SETTLED: (),
    OrderStatus.REFUNDED: (),
}

# 终态集合由流转表推导（无出边的状态即终态），保持单一数据源。
TERMINAL_STATUSES: frozenset[OrderStatus] = frozenset(
    status for status, targets in _TRANSITIONS.items() if not targets
)


def is_valid_transition(from_status: OrderStatus, to_status: OrderStatus) -> bool:
    """判断 from_status → to_status 是否为合法流转。

    流转表里没有的组合一律返回 False（含同状态自流转、跨状态跳跃、
    以及不属于 12 个状态的取值），不存在默认放行的兜底分支。
    """
    return to_status in _TRANSITIONS.get(from_status, ())


def assert_transition(from_status: OrderStatus, to_status: OrderStatus) -> None:
    """断言状态流转合法；非法则抛 OrderTransitionError。"""
    if not is_valid_transition(from_status, to_status):
        raise OrderTransitionError(from_status, to_status)


def allowed_next_statuses(from_status: OrderStatus) -> list[OrderStatus]:
    """返回该状态可流转到的状态列表，供前端与文档使用。

    终态返回空列表。每次返回新列表，调用方修改不会影响状态机。
    """
    return list(_TRANSITIONS.get(from_status, ()))
