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

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import OrderStatus

__all__ = ["OrderSummary", "PlaceOrderRequest"]


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
