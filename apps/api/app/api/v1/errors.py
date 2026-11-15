"""service 异常 -> HTTP 状态码的显式映射。

映射原则：

- **404**：资源不存在，或资源不属于当前用户。两者共用同一个异常、同一句话
  （见 ``services/errors.py`` 的 ``AddressNotFoundError``），
  不让调用方靠错误差异探测他人资源是否存在。
- **409**：状态冲突——资源被占用 / 已停用 / 库存不足 / 时段不可约。
  这类错误重试有意义（换个时间、换个时段再来）。
- **503**：服务端自己的问题，重试也有意义（订单号冲突重试 3 次仍冲突）。
- **400**：兜底的业务异常，客户端改请求内容才可能解决。
- **PricingError 不在表里**：它表示服务端数据异常（价格是脏数据），
  不是客户端的问题，所以让它原样冒泡成 500，不翻译成 4xx。
  把服务端数据问题报成 4xx，会让调用方以为重发请求有用。

401 不在这张表里：鉴权失败由依赖直接抛 HTTPException，走 FastAPI 自带的处理。
"""
from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

from app.domain.slot_rule import SlotInvalidError, SlotNotReservableError
from app.services.errors import (
    AddressInUseError,
    AddressNotFoundError,
    CatalogError,
    CatalogNotFoundError,
    DispatchError,
    DispatchForbiddenError,
    InvalidOrderStateError,
    ItemInactiveError,
    ItemNotFoundError,
    MasterActionError,
    MasterActionForbiddenError,
    MasterActionInvariantError,
    MasterNotDispatchableError,
    MasterNotFoundError,
    MasterOrderStatusNotAllowedError,
    MasterQueryError,
    MasterQueryForbiddenError,
    MasterStatusNotSettableError,
    OrderNoConflictError,
    OrderNotFoundError,
    PlaceOrderError,
    ServiceFlowError,
    ServiceFlowForbiddenError,
    ServiceFlowInvariantError,
    SettlementError,
    SettlementForbiddenError,
    SettlementInvariantError,
    SettlementNotFoundError,
    SlotItemMismatchError,
    SlotNotFoundError,
    SlotNotInFutureError,
)

__all__ = [
    "CATALOG_GENERIC_DETAIL",
    "DISPATCH_GENERIC_DETAIL",
    "EXCEPTION_STATUS_MAP",
    "GENERIC_DETAIL",
    "MASTER_ACTION_GENERIC_DETAIL",
    "MASTER_QUERY_GENERIC_DETAIL",
    "SERVICE_FLOW_GENERIC_DETAIL",
    "SETTLEMENT_GENERIC_DETAIL",
    "catalog_error_handler",
    "dispatch_error_handler",
    "master_action_error_handler",
    "master_query_error_handler",
    "place_order_error_handler",
    "service_flow_error_handler",
    "settlement_error_handler",
    "status_for",
]


# 异常类 -> HTTP 状态码。这张表是唯一的映射事实来源。
EXCEPTION_STATUS_MAP: dict[type[Exception], int] = {
    # 资源不存在（或不属于当前用户）
    AddressNotFoundError: 404,
    ItemNotFoundError: 404,
    SlotNotFoundError: 404,
    OrderNotFoundError: 404,
    # 地址被订单引用，删不掉：换个地址 / 先处理订单再来是可行的应对
    AddressInUseError: 409,
    # 状态冲突
    ItemInactiveError: 409,
    SlotNotInFutureError: 409,
    SlotItemMismatchError: 409,
    SlotInvalidError: 409,
    SlotNotReservableError: 409,
    InvalidOrderStateError: 409,
    # 订单号重试上限内仍冲突：服务端问题，重试有意义
    OrderNoConflictError: 503,
    # 派单：没有服务商归属 / 角色不对
    DispatchForbiddenError: 403,
    # 派单：师傅不存在，或不属于当前服务商
    # 「不存在」与「属于别家」共用同一个异常，响应也完全一样，
    # 调用方无法靠报错差异探测别家师傅（R1）
    MasterNotFoundError: 404,
    # 派单：本商师傅当前不可接单（停用 / 休假 / 未审核）
    # 换个师傅派是可行的应对 -> 409，不是 404 也不是 500
    MasterNotDispatchableError: 409,
    # 师傅状态管理：请求的状态不允许被设置（PENDING 等）
    # 属于「客户端改请求内容才可能解决」-> 400
    MasterStatusNotSettableError: 400,
    # 师傅接单/拒单：账号没有师傅身份，或身份与服务商归属不一致
    MasterActionForbiddenError: 403,
    # 师傅接单/拒单：内部一致性被打破（服务端 bug，不是客户端的问题）
    MasterActionInvariantError: 500,
    # 师傅端查询：角色不对 / 没有师傅身份 / 身份与服务商归属不一致
    MasterQueryForbiddenError: 403,
    # 师傅端查询：状态不在「三种工作分组」里
    # 客户端改了请求内容才可能解决 -> 400
    MasterOrderStatusNotAllowedError: 400,
    # 服务流转：角色不对 / 没有师傅身份 / 身份与服务商归属不一致
    ServiceFlowForbiddenError: 403,
    # 服务流转：内部一致性被打破（服务端 bug，不是客户端的问题）
    ServiceFlowInvariantError: 500,
    # 结算确认：角色不对 / 没有财务权限
    SettlementForbiddenError: 403,
    # 结算确认：结算单不存在，或已经不是「待结算」
    # 「不存在」与「已被确认」共用同一个异常，响应也完全一样，
    # 调用方无法靠报错差异探测结算单的状态
    SettlementNotFoundError: 404,
    # 结算确认：内部一致性被打破（服务端 bug，不是客户端的问题）
    SettlementInvariantError: 500,
    # 目录查询：品类不存在，或已停用（「不存在」与「已停用」共用一句话）
    CatalogNotFoundError: 404,
    # 兜底：其余业务异常
    PlaceOrderError: 400,
    DispatchError: 400,
    MasterActionError: 400,
    MasterQueryError: 400,
    ServiceFlowError: 400,
    SettlementError: 400,
    CatalogError: 400,
}

# 兜底文案。用于 PlaceOrderError 基类——它的消息可能内嵌数据库错误原文
# （见 services/place_order.py 的完整性冲突分支），不能原样回给客户端。
GENERIC_DETAIL = "下单失败"

# 派单的兜底文案（同理：基类的消息可能内嵌服务端内部信息）
DISPATCH_GENERIC_DETAIL = "派单失败"

# 师傅接单/拒单的兜底文案
MASTER_ACTION_GENERIC_DETAIL = "操作失败"

# 师傅端查询（我的订单 / 我的资料）的兜底文案
MASTER_QUERY_GENERIC_DETAIL = "查询失败"

# 服务流转（开工 / 完工 / 确认完成）的兜底文案
SERVICE_FLOW_GENERIC_DETAIL = "操作失败"

# 结算确认的兜底文案
SETTLEMENT_GENERIC_DETAIL = "结算确认失败"

# 目录查询的兜底文案
CATALOG_GENERIC_DETAIL = "查询失败"


def status_for(exc: BaseException) -> int:
    """返回异常对应的 HTTP 状态码。

    按 MRO 从最具体的子类往上找，所以 ``OrderNoConflictError``
    （``PlaceOrderError`` 的子类）命中 503，而不是兜底的 400。
    """
    for cls in type(exc).__mro__:
        status_code = EXCEPTION_STATUS_MAP.get(cls)
        if status_code is not None:
            return status_code
    return EXCEPTION_STATUS_MAP[PlaceOrderError]


async def place_order_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """把下单相关的业务异常翻译成 HTTP 响应。

    响应体统一是 ``{"detail": ...}``。
    """
    detail = _detail_for(exc)
    return JSONResponse(
        status_code=status_for(exc),
        content={"detail": detail},
    )


async def dispatch_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """把派单相关的业务异常翻译成 HTTP 响应。

    响应体统一是 ``{"detail": ...}``。
    """
    detail = DISPATCH_GENERIC_DETAIL if type(exc) is DispatchError else (str(exc) or DISPATCH_GENERIC_DETAIL)
    return JSONResponse(
        status_code=status_for(exc),
        content={"detail": detail},
    )


async def master_action_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """把师傅接单 / 拒单相关的业务异常翻译成 HTTP 响应。

    响应体统一是 ``{"detail": ...}``。
    """
    detail = (
        MASTER_ACTION_GENERIC_DETAIL
        if type(exc) is MasterActionError
        else (str(exc) or MASTER_ACTION_GENERIC_DETAIL)
    )
    return JSONResponse(
        status_code=status_for(exc),
        content={"detail": detail},
    )


async def master_query_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """把师傅端查询相关的业务异常翻译成 HTTP 响应。

    响应体统一是 ``{"detail": ...}``。
    """
    detail = (
        MASTER_QUERY_GENERIC_DETAIL
        if type(exc) is MasterQueryError
        else (str(exc) or MASTER_QUERY_GENERIC_DETAIL)
    )
    return JSONResponse(
        status_code=status_for(exc),
        content={"detail": detail},
    )


async def service_flow_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """把服务流转相关的业务异常翻译成 HTTP 响应。

    响应体统一是 ``{"detail": ...}``。
    """
    detail = (
        SERVICE_FLOW_GENERIC_DETAIL
        if type(exc) is ServiceFlowError
        else (str(exc) or SERVICE_FLOW_GENERIC_DETAIL)
    )
    return JSONResponse(
        status_code=status_for(exc),
        content={"detail": detail},
    )


async def settlement_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """把结算确认相关的业务异常翻译成 HTTP 响应。

    响应体统一是 ``{"detail": ...}``。
    """
    detail = (
        SETTLEMENT_GENERIC_DETAIL
        if type(exc) is SettlementError
        else (str(exc) or SETTLEMENT_GENERIC_DETAIL)
    )
    return JSONResponse(
        status_code=status_for(exc),
        content={"detail": detail},
    )


def _detail_for(exc: BaseException) -> str:
    """决定回给客户端的文案。

    具体业务异常的消息是自己写的业务描述（不含归属信息），可以原样回；
    ``PlaceOrderError`` 基类的消息可能带着数据库错误原文，一律换成通用文案。
    """
    if type(exc) is PlaceOrderError:
        return GENERIC_DETAIL
    return str(exc) or GENERIC_DETAIL


async def catalog_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """把目录查询相关的业务异常翻译成 HTTP 响应。

    响应体统一是 ``{"detail": ...}``。
    """
    detail = (
        CATALOG_GENERIC_DETAIL
        if type(exc) is CatalogError
        else (str(exc) or CATALOG_GENERIC_DETAIL)
    )
    return JSONResponse(
        status_code=status_for(exc),
        content={"detail": detail},
    )
