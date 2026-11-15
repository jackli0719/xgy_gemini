"""服务商侧只读查询的响应 schema。

两个接口（待派单列表 / 本商师傅列表）**都只从 token 取服务商归属**：
``require_provider_scope`` 保证当前账号是服务商侧角色且带着 provider_id，
service 直接拿它过滤。请求里**没有 provider_id 参数**——客户端自报归属
等于让它自己挑租户，隔离当场失效（R1）。

响应里也不往外发别家的东西：订单列表只含本商可派的订单（含公共待派单池），
师傅列表只含本商师傅。
"""
from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import MasterStatus, OrderStatus, PayStatus

__all__ = [
    "ProviderMasterItem",
    "ProviderMasterListResponse",
    "ProviderOrderItem",
    "ProviderOrderListResponse",
]


class ProviderOrderItem(BaseModel):
    """待派单列表里的一笔订单。

    带 ``id``（数字主键）：派单接口 ``POST /orders/{order_id}/dispatch``
    收的是数字 id，不是订单号——前端拿它拼 URL，不用再查一次。
    """

    model_config = ConfigDict(extra="forbid")

    id: int = Field(..., description="订单 ID（派单接口用它）")
    order_no: str = Field(..., description="订单号")
    status: OrderStatus = Field(..., description="订单状态")
    pay_status: PayStatus = Field(..., description="支付状态")
    amount: Decimal = Field(..., description="订单金额")
    item_id: int = Field(..., description="服务项 ID")
    item_name: str = Field(..., description="服务项名称")
    slot_date: date = Field(..., description="预约日期")
    slot_start_time: time = Field(..., description="预约开始时间")
    created_at: datetime = Field(..., description="下单时间")


class ProviderOrderListResponse(BaseModel):
    """待派单列表（一页 + 总数）。

    带 total 是因为前端要显示「共 N 条」；只回一个数组的话，
    客户端只能靠「这页有没有满 limit」去猜还有没有下一页。
    """

    model_config = ConfigDict(extra="forbid")

    items: list[ProviderOrderItem] = Field(..., description="当前页的订单")
    total: int = Field(..., description="符合条件的订单总数（不受分页影响）")
    limit: int = Field(..., description="本次生效的每页条数（上限 100）")
    offset: int = Field(..., description="本次跳过的条数")


class ProviderMasterItem(BaseModel):
    """本商师傅的一项。

    ``rating`` 可以是空：还没被评价过的师傅没有分数。
    """

    model_config = ConfigDict(extra="forbid")

    id: int = Field(..., description="师傅 ID（派单接口用它）")
    real_name: str = Field(..., description="师傅姓名")
    rating: Decimal | None = Field(default=None, description="评分（0~5，可空）")
    status: MasterStatus = Field(..., description="师傅状态")


class ProviderMasterListResponse(BaseModel):
    """本商师傅列表。"""

    model_config = ConfigDict(extra="forbid")

    items: list[ProviderMasterItem] = Field(..., description="师傅列表")
    total: int = Field(..., description="师傅总数")
