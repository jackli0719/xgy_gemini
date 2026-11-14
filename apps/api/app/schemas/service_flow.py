"""服务流转（开工 / 完工 / 确认完成）接口的响应 schema。

三个动作都是「推进已有订单的状态」，不是创建资源，所以响应里只有
订单号、当前状态、完工时间——**没有任何身份字段**：

- 师傅身份由服务端从 token 的 user_id 查 master 表得到；
- 客户身份就是 token 里的 user_id。

客户端不能在请求体里自报「我替谁确认」（请求体里根本没有身份字段）。
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import OrderStatus

__all__ = ["ServiceFlowResult"]


class ServiceFlowResult(BaseModel):
    """服务流转动作执行后的订单状态。"""

    model_config = ConfigDict(extra="forbid")

    order_no: str = Field(..., description="订单号")
    status: OrderStatus = Field(..., description="流转后的订单状态")
    # 只有「完成」才有完工时间：开工 / 完工之后订单还没真正做完
    completed_at: datetime | None = Field(
        None, description="完工时间（订单完成时非空）"
    )
