"""支付回调的接口层 schema。

请求体只允许 order_no：支付回调不传金额、不传状态——
金额是下单时的快照，状态由服务端按状态机流转，客户端说了也不算。
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import OrderStatus, PayStatus

__all__ = ["MockPayNotifyRequest", "MockPayResult"]


class MockPayNotifyRequest(BaseModel):
    """mock 支付回调的请求体。"""

    model_config = ConfigDict(extra="forbid")

    order_no: str = Field(
        ...,
        min_length=1,
        max_length=32,
        description="订单号",
    )


class MockPayResult(BaseModel):
    """mock 支付回调的响应体。

    只回三个字段：订单号、订单状态、支付状态。不回金额、不回用户信息。
    """

    model_config = ConfigDict(extra="forbid")

    order_no: str
    status: OrderStatus
    pay_status: PayStatus
