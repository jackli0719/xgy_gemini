"""师傅接单 / 拒单接口的请求 / 响应 schema。

**请求体里没有任何身份字段**：师傅身份（master_id）由服务端从
token 里的 user_id 查 master 表得到，客户端不能自选「我是哪个师傅」（R1）。
拒单的请求体只有一个字段：reason（拒单原因），它会原样落进状态流转日志。
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import OrderStatus

__all__ = ["AcceptResult", "RejectRequest", "RejectResult"]


class AcceptResult(BaseModel):
    """接单成功后的结果。"""

    model_config = ConfigDict(extra="forbid")

    order_no: str = Field(..., description="订单号")
    status: OrderStatus = Field(..., description="订单状态")
    master_id: int = Field(..., description="承接订单的师傅 ID")


class RejectRequest(BaseModel):
    """拒单请求体。"""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(
        ...,
        min_length=1,
        max_length=512,
        description="拒单原因，会原样写进订单状态流转日志",
    )


class RejectResult(BaseModel):
    """拒单成功后的结果。

    master_id 为空：拒单后订单退回「待派单」，当前没有承接师傅。
    """

    model_config = ConfigDict(extra="forbid")

    order_no: str = Field(..., description="订单号")
    status: OrderStatus = Field(..., description="订单状态")
    master_id: int | None = Field(..., description="承接订单的师傅 ID（拒单后为空）")
