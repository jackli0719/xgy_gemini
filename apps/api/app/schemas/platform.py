"""平台侧服务商管理的请求与响应 schema。

平台侧与服务商侧的区别就在**归属从哪来**：

- 服务商侧的接口，归属由 token 决定（``require_provider_scope``），
  请求里**没有 provider_id 参数**——不是「约定别传」，是「传不进来」。
- 平台侧要管**所有**服务商，所以「管哪一个」是请求的一部分：
  路径里的 ``{provider_id}``。但**操作人身份仍然只从 token 来**
  （``require_platform_admin``）：客户端能说「我要改 3 号服务商」，
  但不能说自己是谁。

请求体里出现 provider_id 一律 422（``extra="forbid"``）：
归属由服务端按路径决定，客户端自报归属等于让它自己挑对象。
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import ProviderStatus, SettableProviderStatus, UserRole

__all__ = [
    "CreateProviderAdminRequest",
    "CreateProviderRequest",
    "PlatformProviderItem",
    "PlatformProviderListResponse",
    "ProviderAdminItem",
    "UpdateProviderStatusRequest",
]


class PlatformProviderItem(BaseModel):
    """平台侧看到的一条服务商。"""

    model_config = ConfigDict(extra="forbid")

    id: int = Field(..., description="服务商 ID")
    name: str = Field(..., description="服务商名称")
    contact_phone: str = Field(..., description="联系电话")
    commission_rate: Decimal = Field(..., description="佣金比例（0~1）")
    status: ProviderStatus = Field(..., description="服务商状态")
    created_at: datetime = Field(..., description="建档时间")


class PlatformProviderListResponse(BaseModel):
    """服务商列表（一页 + 总数）。"""

    model_config = ConfigDict(extra="forbid")

    items: list[PlatformProviderItem] = Field(..., description="当前页的服务商")
    total: int = Field(..., description="符合条件的服务商总数（不受分页影响）")
    page: int = Field(..., description="当前页码（从 1 开始）")
    limit: int = Field(..., description="本次生效的每页条数（上限 100）")


class CreateProviderRequest(BaseModel):
    """新建服务商的请求体。

    **只有这三个字段**：服务商归属（也就是「归谁管」）由平台侧决定，
    不在请求体里；状态也不在——新建一律「待审核」（PENDING），
    要审核通过再调改状态接口。
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=128, description="服务商名称")
    contact_phone: str = Field(
        ...,
        min_length=1,
        max_length=32,
        description="联系电话",
    )
    commission_rate: Decimal = Field(
        ...,
        ge=0,
        le=1,
        description="佣金比例（0~1，例如 0.15 表示 15%）",
    )


class UpdateProviderStatusRequest(BaseModel):
    """改服务商状态的请求体。

    ``status`` 用的是**窄枚举** ``SettableProviderStatus``（ACTIVE / FROZEN），
    所以接口这一层就把「PENDING 不许设置」变成 422。
    但这只是一道防线：service 那边按同一份枚举再挡一次
    （见 app.services.platform_provider），免得有人绕过接口层直接调 service。
    """

    model_config = ConfigDict(extra="forbid")

    status: SettableProviderStatus = Field(..., description="要把服务商改成什么状态")


class CreateProviderAdminRequest(BaseModel):
    """给某个服务商建管理员账号的请求体。

    **只有手机号**：账号的角色（PROVIDER_ADMIN）与归属（provider_id）
    都由服务端按路径与规则填，客户端说了不算。
    """

    model_config = ConfigDict(extra="forbid")

    phone: str = Field(
        ...,
        pattern=r"^[0-9]{6,20}$",
        description="管理员登录用的手机号（纯数字）",
    )


class ProviderAdminItem(BaseModel):
    """刚建出来的服务商管理员账号。"""

    model_config = ConfigDict(extra="forbid")

    id: int = Field(..., description="用户 ID")
    phone: str = Field(..., description="登录手机号")
    role: UserRole = Field(..., description="用户角色（PROVIDER_ADMIN）")
    provider_id: int = Field(..., description="归属的服务商 ID")
    created_at: datetime = Field(..., description="建号时间")
