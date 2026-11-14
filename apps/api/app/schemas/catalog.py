"""品类 / 服务项 / 时段余量的响应 schema。

这三个接口都是**只读**的公开信息：品类树、服务项、可预约时段。
响应里不含任何金额以外的业务判断，也不含用户身份相关的字段——
身份只影响「能看什么」（订单），不影响「目录长什么样」。

``CategoryNode.children`` 是自引用：品类表用 parent_id 自引用形成树，
父品类停用时整棵子树一起下架（见 app.services.user_queries）。
"""
from __future__ import annotations

import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "CategoryNode",
    "ServiceItemSummary",
    "SlotAvailability",
]


class CategoryNode(BaseModel):
    """品类节点（含子品类）。

    ``children`` 只挂**直接下级**；子品类自己的子品类递归嵌在它里面。
    停用的品类不出现在树里（它的子树也一起不出现）。
    """

    model_config = ConfigDict(extra="forbid")

    id: int = Field(..., description="品类 ID")
    name: str = Field(..., description="品类名称")
    parent_id: int | None = Field(..., description="父品类 ID，一级品类为空")
    sort_order: int = Field(..., description="排序值，越小越靠前")
    children: list["CategoryNode"] = Field(
        default_factory=list, description="子品类"
    )


# 自引用：类定义完之后补一次解析
CategoryNode.model_rebuild()


class ServiceItemSummary(BaseModel):
    """服务项摘要（可下单的具体服务与价格）。"""

    model_config = ConfigDict(extra="forbid")

    id: int = Field(..., description="服务项 ID")
    category_id: int = Field(..., description="所属品类 ID")
    name: str = Field(..., description="服务项名称")
    base_price: Decimal = Field(..., description="基准价（服务端按它快照下单金额）")
    duration_min: int = Field(..., description="服务时长（分钟）")


class SlotAvailability(BaseModel):
    """某个时段的可预约情况。

    ``available`` = capacity - used，只返回 available > 0 的时段。
    容量与已占用数一起返回，是为了让前端能显示「还剩几个」，
    而不是让前端自己算一遍（两边的口径容易不一致）。
    """

    model_config = ConfigDict(extra="forbid")

    id: int = Field(..., description="时段 ID")
    item_id: int = Field(..., description="服务项 ID")
    # 列名 date / start_time / end_time 与 datetime 的类型名同名，
    # 注解一律走 datetime.xxx 显式限定，避免同名遮蔽导致类型解析出错
    date: datetime.date = Field(..., description="时段日期")
    start_time: datetime.time = Field(..., description="开始时间")
    end_time: datetime.time = Field(..., description="结束时间")
    capacity: int = Field(..., description="总容量")
    used: int = Field(..., description="已占用数")
    available: int = Field(..., description="剩余可预约数 = capacity - used")
