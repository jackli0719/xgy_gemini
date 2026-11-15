"""师傅端查询接口的请求 / 响应 schema。

这三个接口（我的订单列表 / 订单详情 / 我的资料）**都只从 token 取身份**：
``require_master_scope`` 保证当前账号是 MASTER 角色，
service 再按 ``current_user.user_id`` 查 master 表得到师傅身份。
请求里**没有 master_id / user_id / provider_id 参数**——客户端自报身份
等于让它自己挑租户，隔离当场失效（R1）。

响应里也不往外发别家的东西：订单只返回派给我的，
「订单不存在」与「订单不是我的」是同一个 404、同一句话（404 同构）。

``extra="forbid"``：多带一个字段直接 422，而不是被静默忽略。
"""
from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import MasterStatus, OrderStatus

__all__ = [
    "MasterOrderDetail",
    "MasterOrderItem",
    "MasterOrderListResponse",
    "MasterProfile",
]


class MasterOrderItem(BaseModel):
    """师傅端订单列表里的一项。

    不含 master_id / provider_id：师傅知道自己是谁，不需要知道订单内部
    怎么归属的（也不该由客户端去猜）。
    """

    model_config = ConfigDict(extra="forbid")

    order_no: str = Field(..., description="订单号")
    status: OrderStatus = Field(..., description="订单状态")
    amount: Decimal = Field(..., description="订单金额")
    item_id: int = Field(..., description="服务项 ID")
    item_name: str = Field(..., description="服务项名称")
    slot_date: date = Field(..., description="预约日期")
    slot_start_time: time = Field(..., description="预约开始时间")
    slot_end_time: time = Field(..., description="预约结束时间")
    created_at: datetime = Field(..., description="下单时间")


class MasterOrderListResponse(BaseModel):
    """订单列表（一页 + 总数）。

    带 total 是因为前端要显示「共 N 条」并判断还有没有下一页；
    只回一个数组的话，客户端只能靠「这页有没有满 limit」去猜。
    """

    model_config = ConfigDict(extra="forbid")

    items: list[MasterOrderItem] = Field(..., description="当前页的订单")
    total: int = Field(..., description="符合条件的订单总数（不受分页影响）")
    limit: int = Field(..., description="本次生效的每页条数（上限 100）")
    offset: int = Field(..., description="本次跳过的条数")


class MasterOrderDetail(MasterOrderItem):
    """订单详情：多了客户联系方式与上门地址。

    师傅要上门服务，得知道去哪儿、找谁——所以详情里带地址与电话。
    可见范围由服务端保证：只有派给他的订单才查得到（404 同构）。
    """

    model_config = ConfigDict(extra="forbid")

    id: int = Field(..., description="订单 ID")
    slot_id: int = Field(..., description="预约时段 ID")
    customer_contact: str = Field(..., description="客户称呼")
    customer_phone: str = Field(..., description="客户电话")
    address_region: str = Field(..., description="地址所在区域")
    address_detail: str = Field(..., description="详细地址")


class MasterProfile(BaseModel):
    """师傅自己的资料。

    ``rating`` 可以是空：还没被评价过的师傅没有分数。
    ``provider_name`` 是所属服务商的名称（师傅要知道自己是哪家的）。
    """

    model_config = ConfigDict(extra="forbid")

    real_name: str = Field(..., description="师傅姓名")
    rating: Decimal | None = Field(default=None, description="评分（0~5，可空）")
    status: MasterStatus = Field(..., description="师傅状态")
    provider_name: str = Field(..., description="所属服务商名称")
