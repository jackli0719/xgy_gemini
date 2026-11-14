"""派单接口的请求 / 响应 schema。

请求体只有一个字段：master_id（要派给哪个师傅）。

**provider_id 不在请求体里**，这是接口层最关键的一条边界：
服务商归属来自已验签的 token（``CurrentUser.provider_id``），
客户端自报一个 provider_id 等于让它自己挑租户，隔离当场失效（R1）。
带着 provider_id 发请求会被 ``extra="forbid"`` 直接 422 掉，
而不是被静默忽略——静默忽略会让人以为字段生效了。
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import OrderStatus

__all__ = ["DispatchRequest", "DispatchResult"]


class DispatchRequest(BaseModel):
    """派单请求体。"""

    model_config = ConfigDict(extra="forbid")

    master_id: int = Field(..., gt=0, description="承接订单的师傅 ID")


class DispatchResult(BaseModel):
    """派单成功后的结果。"""

    model_config = ConfigDict(extra="forbid")

    order_no: str = Field(..., description="订单号")
    status: OrderStatus = Field(..., description="订单状态")
    master_id: int = Field(..., description="承接订单的师傅 ID")
