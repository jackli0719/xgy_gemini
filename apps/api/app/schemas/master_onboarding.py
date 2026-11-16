"""师傅入驻接口的请求 / 响应 schema。

**请求体里为什么没有 provider_id**：师傅申请时填的是「我想加入哪家」
（``target_provider_id``），那是**申请内容**，不是「当前作用域」。
真正的归属由平台审核确认——它不是一个客户端可以自报的东西，
所以这里刻意不用 ``provider_id`` 这个名字（全仓 openapi 契约测试也
禁止请求体出现该字段名）。

**身份字段一个都不在请求体里**：师傅身份来自 token
（``current_user.user_id``），客户端自报身份等于让它自己挑账号（R1）。
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import MasterStatus, OnboardingDecision

__all__ = [
    "JoinableProviderItem",
    "JoinableProviderListResponse",
    "OnboardingApplicationItem",
    "OnboardingApplicationListResponse",
    "ReviewOnboardingRequest",
    "ReviewOnboardingResponse",
    "SubmitOnboardingRequest",
]


class JoinableProviderItem(BaseModel):
    """可以申请加入的服务商。

    只有 id 与名称：佣金率、联系电话是平台侧 / 服务商侧的信息，
    入驻阶段用不上。
    """

    model_config = ConfigDict(extra="forbid")

    id: int = Field(..., description="服务商 ID")
    name: str = Field(..., description="服务商名称")


class JoinableProviderListResponse(BaseModel):
    """可加入的服务商列表。"""

    model_config = ConfigDict(extra="forbid")

    items: list[JoinableProviderItem] = Field(..., description="可加入的服务商")


class SubmitOnboardingRequest(BaseModel):
    """提交入驻申请的请求体。

    只有两个字段：师傅姓名与想加入的服务商。
    状态**不在**——登记一律「待审核」（PENDING），要审核通过才入职。
    """

    model_config = ConfigDict(extra="forbid")

    real_name: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="师傅姓名",
    )
    target_provider_id: int = Field(
        ...,
        ge=1,
        description="申请加入的服务商 ID（必须是可加入状态）",
    )


class OnboardingApplicationItem(BaseModel):
    """一条入驻申请。

    平台侧看得到申请人的手机号（要联系本人核实资质）；
    师傅自己看自己那一条时也会拿到它（同一个模型，手机号就是自己的）。
    """

    model_config = ConfigDict(extra="forbid")

    id: int = Field(..., description="师傅 ID（审核接口用它）")
    real_name: str = Field(..., description="师傅姓名")
    phone: str = Field(..., description="申请人手机号")
    status: MasterStatus = Field(..., description="入驻状态")
    provider_id: int = Field(..., description="所属服务商 ID")
    provider_name: str = Field(..., description="所属服务商名称")
    created_at: datetime = Field(..., description="提交申请的时间")


class OnboardingApplicationListResponse(BaseModel):
    """入驻申请列表（一页 + 总数）。"""

    model_config = ConfigDict(extra="forbid")

    items: list[OnboardingApplicationItem] = Field(..., description="当前页的申请")
    total: int = Field(..., description="符合条件的申请总数（不受分页影响）")
    page: int = Field(..., description="当前页码（从 1 开始）")
    limit: int = Field(..., description="本次生效的每页条数（上限 100）")


class ReviewOnboardingRequest(BaseModel):
    """平台审核入驻申请的请求体。

    ``decision`` 只有两种取值（APPROVE / REJECT）——它是业务规则，
    定义在 ``app.models.enums.OnboardingDecision``（事实来源）。
    """

    model_config = ConfigDict(extra="forbid")

    decision: OnboardingDecision = Field(
        ...,
        description="审核结论：APPROVE（通过）/ REJECT（驳回）",
    )
    target_provider_id: int | None = Field(
        default=None,
        ge=1,
        description=(
            "改判到另一家服务商（可选）。"
            "不传则沿用申请里选的那家；传了必须是可加入状态的服务商"
        ),
    )
    reason: str | None = Field(
        default=None,
        max_length=500,
        description="审核备注（可选，写进审计日志）",
    )


class ReviewOnboardingResponse(BaseModel):
    """审核结果。

    ``status`` 为空表示「驳回」：驳回是把这一行删掉（没通过审核 = 没入职），
    所以没有状态可回。审核结论留痕在审计日志里。
    """

    model_config = ConfigDict(extra="forbid")

    id: int = Field(..., description="师傅 ID")
    real_name: str = Field(..., description="师傅姓名")
    status: MasterStatus | None = Field(
        default=None,
        description="审核后的状态；为空表示已驳回（该行已删除）",
    )
    provider_id: int = Field(..., description="所属服务商 ID")
    provider_name: str = Field(..., description="所属服务商名称")
    created_at: datetime = Field(..., description="提交申请的时间")
