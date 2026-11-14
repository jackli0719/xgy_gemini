"""预约时段库存扣减的领域判定（纯逻辑）。

职责边界：只回答「给定 capacity / used / count，能否再扣减 count 个」。
不碰数据库、不做并发控制、不写日志、不取时间戳、不读全局配置。

并发安全由 T-07b-2b 负责——那里用条件 UPDATE
（`UPDATE ... WHERE used + count <= capacity`）在数据库层原子扣减。
本模块的判定只是业务规则的单一事实来源，不能当作并发保障使用：
两个并发请求都可能在本模块判定通过，再由 T-07b-2b 的条件 UPDATE 兜底。
"""
from __future__ import annotations

__all__ = [
    "SlotError",
    "SlotInvalidError",
    "SlotNotReservableError",
    "assert_reservable",
    "available",
    "can_reserve",
]


class SlotError(Exception):
    """时段库存相关错误的基类。

    消息统一带上 capacity / used / count 三个数值，便于排查。
    """

    def __init__(self, capacity: int, used: int, count: int, reason: str) -> None:
        self.capacity = capacity
        self.used = used
        self.count = count
        self.reason = reason
        super().__init__(
            "时段预约失败（{}）：capacity={}, used={}, count={}".format(
                reason, capacity, used, count
            )
        )


class SlotInvalidError(SlotError):
    """参数或库存数据非法。

    触发条件：count <= 0、capacity <= 0、used < 0、used > capacity。
    """


class SlotNotReservableError(SlotError):
    """库存不足，无法再扣减。

    触发条件：参数与数据都合法，但 used + count > capacity。
    """


def available(capacity: int, used: int) -> int:
    """返回剩余可预约数量。

    used > capacity 属异常数据，此时返回 0，不返回负数。
    """
    remaining = capacity - used
    return remaining if remaining > 0 else 0


def can_reserve(capacity: int, used: int, count: int = 1) -> bool:
    """判断能否再扣减 count 个。

    以下条件必须同时成立才返回 True：
    count > 0、capacity > 0、used >= 0、used <= capacity、used + count <= capacity。
    任一条不成立一律返回 False（异常数据也不放行）。
    """
    if count <= 0:
        return False
    if capacity <= 0:
        return False
    if used < 0:
        return False
    if used > capacity:
        return False
    return used + count <= capacity


def assert_reservable(capacity: int, used: int, count: int = 1) -> None:
    """断言可以扣减 count 个；不可扣减则抛异常。

    两类失败原因分开：
    - 参数或数据非法（count <= 0 / capacity <= 0 / used < 0 / used > capacity）
      抛 SlotInvalidError；
    - 数据合法但库存不足（used + count > capacity）抛 SlotNotReservableError。
    """
    if count <= 0 or capacity <= 0 or used < 0 or used > capacity:
        raise SlotInvalidError(capacity, used, count, "数据或参数非法")
    if used + count > capacity:
        raise SlotNotReservableError(capacity, used, count, "库存不足")
