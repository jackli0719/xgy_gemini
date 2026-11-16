"""平台侧结算单列表的响应 schema（PLAT-03）。

**响应里只有给人看的字段**：结算单 id、服务商名、结算周期、金额三件套、
状态、确认时间。内部字段（确认人 id、创建 / 更新时间戳、佣金率）
不进接口——它们是服务端的事，页面用不上。

**金额是 Decimal**（OpenAPI 里映射成 string）：前端要自己转，
不要当 number 直接用（精度会掉）。
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import SettlementStatus

__all__ = [
    "PlatformSettlementItem",
    "PlatformSettlementListResponse",
    "PlatformSettlementProviderOption",
]


class PlatformSettlementItem(BaseModel):
    """平台财务看到的一张结算单。"""

    model_config = ConfigDict(extra="forbid")

    id: int = Field(..., description="结算单 ID")
    provider_name: str = Field(..., description="服务商名称")
    period_start: date = Field(..., description="结算周期开始日（含）")
    period_end: date = Field(..., description="结算周期结束日（含）")
    total_amount: Decimal = Field(..., description="周期内订单金额合计（客户实付）")
    commission_amount: Decimal = Field(..., description="平台佣金")
    net_amount: Decimal = Field(..., description="服务商实收（合计 - 佣金）")
    status: SettlementStatus = Field(..., description="结算单状态")
    confirmed_at: datetime | None = Field(
        None, description="确认时间；还没确认时为空"
    )


class PlatformSettlementProviderOption(BaseModel):
    """筛选栏里的一个服务商选项。"""

    model_config = ConfigDict(extra="forbid")

    id: int = Field(..., description="服务商 ID")
    name: str = Field(..., description="服务商名称")


class PlatformSettlementListResponse(BaseModel):
    """结算单列表（一页 + 总数 + 筛选用的服务商列表）。"""

    model_config = ConfigDict(extra="forbid")

    items: list[PlatformSettlementItem] = Field(..., description="当前页的结算单")
    total: int = Field(..., description="符合筛选条件的结算单总数（不受分页影响）")
    page: int = Field(..., description="当前页码（从 1 开始）")
    limit: int = Field(..., description="本次生效的每页条数（上限 100）")
    providers: list[PlatformSettlementProviderOption] = Field(
        ...,
        description=(
            "筛选栏用的服务商列表（有过结算单的服务商）——"
            "放在这里是因为平台侧的服务商列表接口只对平台管理员开放，"
            "而结算单列表是财务要用的"
        ),
    )
