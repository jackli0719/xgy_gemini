"""下单接口的请求 / 响应 schema。

这里是接口层的第一道安全边界：

- 请求体只接受 item_id / slot_id / address_id 三个字段。
  金额、订单号、状态、派单信息（provider_id / master_id）、以及 user_id
  都不在这里——它们要么由服务端决定，要么根本不该由客户端声明。
- ``extra="forbid"``：请求体多带一个字段（比如 user_id）直接 422，
  而不是被静默忽略。静默忽略会让人以为字段生效了，实际却是另一套行为。
- 响应只回订单摘要。provider_id / master_id 是内部派单信息，
  完整地址属于个人数据，都不往外发。
"""
from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import OrderStatus, PayStatus

__all__ = [
    "OrderDetail",
    "OrderListItem",
    "OrderListResponse",
    "OrderSummary",
    "PlaceOrderRequest",
]


class PlaceOrderRequest(BaseModel):
    """下单请求体。

    字段集合就是 ``{item_id, slot_id, address_id}``，多一个少一个都算破坏契约
    （有测试盯着）。
    """

    model_config = ConfigDict(extra="forbid")

    item_id: int = Field(..., gt=0, description="服务项 ID")
    slot_id: int = Field(..., gt=0, description="预约时段 ID")
    address_id: int = Field(..., gt=0, description="收货地址 ID")


class OrderSummary(BaseModel):
    """下单成功后的订单摘要。"""

    model_config = ConfigDict(extra="forbid")

    id: int = Field(..., description="订单 ID")
    order_no: str = Field(..., description="订单号")
    status: OrderStatus = Field(..., description="订单状态")
    amount: Decimal = Field(..., description="订单金额（服务端按服务项基准价快照）")


# =====================================================================
# 只读查询：我的订单列表 / 订单详情
#
# 与下单响应分开：下单响应只回摘要（刚建完的订单没什么可看的），
# 查询接口才给足信息（服务项名称、预约时段、创建时间）。
#
# 仍然不往外发的：provider_id / master_id（内部派单信息）、
# 完整收货地址（个人数据，这里只给 address_id，地址详情走地址自己的接口）。
# =====================================================================


class OrderListItem(BaseModel):
    """订单列表里的一项。"""

    model_config = ConfigDict(extra="forbid")

    order_no: str = Field(..., description="订单号")
    status: OrderStatus = Field(..., description="订单状态")
    pay_status: PayStatus = Field(..., description="支付状态")
    amount: Decimal = Field(..., description="订单金额")
    item_id: int = Field(..., description="服务项 ID")
    item_name: str = Field(..., description="服务项名称")
    slot_date: date = Field(..., description="预约日期")
    slot_start_time: time = Field(..., description="预约开始时间")
    created_at: datetime = Field(..., description="下单时间")


class OrderListResponse(BaseModel):
    """订单列表（一页 + 总数）。

    带 total 是因为前端要显示「共 N 条」并判断还有没有下一页；
    只回一个数组的话，客户端只能靠「这页有没有满 limit」去猜。
    """

    model_config = ConfigDict(extra="forbid")

    items: list[OrderListItem] = Field(..., description="当前页的订单")
    total: int = Field(..., description="该用户的订单总数（不受分页影响）")
    limit: int = Field(..., description="本次生效的每页条数（上限 100）")
    offset: int = Field(..., description="本次跳过的条数")


class OrderDetail(OrderListItem):
    """订单详情。"""

    model_config = ConfigDict(extra="forbid")

    id: int = Field(..., description="订单 ID")
    slot_id: int = Field(..., description="预约时段 ID")
    slot_end_time: time = Field(..., description="预约结束时间")
    address_id: int = Field(..., description="收货地址 ID")
    # 完成时间：客户确认完成（或自动确认）时才写。
    # 没完成的订单这里是 null——前端据此决定要不要显示「完成时间」。
    completed_at: datetime | None = Field(
        default=None, description="完成时间（未完成时为 null）"
    )
