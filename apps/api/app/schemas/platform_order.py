"""平台侧订单总览的响应 schema。

平台订单总览与用户侧订单列表的**根本区别**：

- 用户侧只看得见自己的单（服务端按 token 里的 user_id 过滤）；
- 平台侧看**全量**：订单不按用户过滤，也不按服务商过滤
  （可以按状态 / 服务商筛选，但那是筛选条件，不是隔离边界）。

请求里出现 user_id 是不允许的——平台侧的特权来自**角色**，
不来自客户端自报的身份（见 app.core.auth.require_platform_staff）。
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import OrderStatus, PayStatus

__all__ = [
    "PlatformOrderItem",
    "PlatformOrderListResponse",
    "PlatformOrderProviderOption",
]


class PlatformOrderItem(BaseModel):
    """平台侧看到的一条订单。"""

    model_config = ConfigDict(extra="forbid")

    id: int = Field(..., description="订单 ID")
    order_no: str = Field(..., description="订单号")
    status: OrderStatus = Field(..., description="订单状态")
    pay_status: PayStatus = Field(..., description="支付状态")
    amount: Decimal = Field(..., description="订单金额")
    user_id: int = Field(..., description="下单用户 ID（平台看全量，不做用户过滤）")
    provider_id: int | None = Field(
        ...,
        description="归属的服务商 ID；还没派单时为空",
    )
    provider_name: str | None = Field(
        ...,
        description="服务商名称；还没派单时为空",
    )
    item_id: int = Field(..., description="服务项 ID")
    item_name: str = Field(..., description="服务项名称")
    created_at: datetime = Field(..., description="下单时间")


class PlatformOrderProviderOption(BaseModel):
    """筛选栏里的一个服务商选项。"""

    model_config = ConfigDict(extra="forbid")

    id: int = Field(..., description="服务商 ID")
    name: str = Field(..., description="服务商名称")


class PlatformOrderListResponse(BaseModel):
    """订单总览（一页 + 总数 + 筛选用的服务商列表）。"""

    model_config = ConfigDict(extra="forbid")

    items: list[PlatformOrderItem] = Field(..., description="当前页的订单")
    total: int = Field(..., description="符合筛选条件的订单总数（不受分页影响）")
    page: int = Field(..., description="当前页码（从 1 开始）")
    limit: int = Field(..., description="本次生效的每页条数（上限 100）")
    providers: list[PlatformOrderProviderOption] = Field(
        ...,
        description=(
            "筛选栏用的服务商列表（有过订单的服务商）——"
            "放在这里是因为平台侧的服务商列表接口只对平台管理员开放，"
            "而订单总览平台运营也要能筛"
        ),
    )
