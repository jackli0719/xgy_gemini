"""下单 / 派单 service 的业务异常。

这些异常表达「客户端输入或服务端数据不满足业务前置条件」，
由 API 层统一映射成 4xx。

领域层已有的异常（app.domain.slot_rule 的 SlotError 树）不重复定义，
下单 service 直接复用，避免同一个语义出现两套类型。
"""
from __future__ import annotations

__all__ = [
    "AddressNotFoundError",
    "DispatchError",
    "DispatchForbiddenError",
    "InvalidOrderStateError",
    "ItemInactiveError",
    "ItemNotFoundError",
    "MasterNotFoundError",
    "OrderNoConflictError",
    "OrderNotFoundError",
    "PlaceOrderError",
    "SlotItemMismatchError",
    "SlotNotFoundError",
    "SlotNotInFutureError",
]


class PlaceOrderError(Exception):
    """下单失败的业务异常基类。"""


class AddressNotFoundError(PlaceOrderError):
    """地址不存在，或不属于当前用户。

    「不存在」与「不属于你」共用同一个异常，消息也不含归属信息——
    否则调用方可以用两者的错误差异探测他人资源是否存在（R5 越权）。
    """


class ItemNotFoundError(PlaceOrderError):
    """服务项不存在。"""


class ItemInactiveError(PlaceOrderError):
    """服务项已停用，不能下单。"""


class SlotNotFoundError(PlaceOrderError):
    """预约时段不存在。"""


class SlotItemMismatchError(PlaceOrderError):
    """预约时段不属于所选服务项。"""


class SlotNotInFutureError(PlaceOrderError):
    """预约时段不是未来时间，不能下单。"""


class OrderNoConflictError(PlaceOrderError):
    """订单号连续冲突，重试上限内仍未拿到可用订单号。"""


class OrderNotFoundError(PlaceOrderError):
    """订单不存在。"""


class InvalidOrderStateError(PlaceOrderError):
    """订单当前状态不允许该操作。

    例如订单已经不是「待支付」，却收到支付回调。
    """


class DispatchError(Exception):
    """派单失败的业务异常基类。

    与 ``PlaceOrderError`` 平级而不是它的子类：派单与下单是两条链路，
    共用一个基类会让「下单失败」的兜底文案套到派单错误上。
    """


class MasterNotFoundError(DispatchError):
    """师傅不存在，或不属于当前服务商。

    「不存在」与「属于别的服务商」共用同一个异常、同一句话——
    否则调用方能靠报错差异探测别家师傅是否存在（R1 租户隔离）。
    """


class DispatchForbiddenError(DispatchError):
    """当前账号没有派单权限。

    典型场景：token 里没有服务商归属（provider_id 为空），
    或者角色不是服务商侧角色。这种情况连订单都查不到就该被挡住。
    """
