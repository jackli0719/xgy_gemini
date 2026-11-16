"""平台侧路由（服务商管理：列表 / 建档 / 改状态 / 建管理员账号）。

接口层只做三件事：校验入参、鉴权、把 service 的结果翻译成 HTTP。
业务判断全在 service 里，这里不重复一遍。

**操作人身份来自 token，不来自请求**（R1）：``require_platform_admin``
保证当前账号是 PLATFORM_ADMIN 角色，审计日志里的操作人由 service 从
``CurrentUser`` 填。请求体里出现 operator / provider_id 之类字段会被
schema 直接 422。

**「管哪一个服务商」是路径参数**：平台侧管的是所有服务商，
``{provider_id}`` 说的是「改哪一家」；但它不是「我是谁」——
身份永远来自 token。

普通用户 / 服务商账号调这几个接口 -> 403 Forbidden，
文案与别处的越权失败一致（不区分「角色不对」还是「没有归属」）。
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query
# 这里的 status 是 HTTP 状态码；下面那个查询参数也叫 status（接口约定），
# 所以 HTTP 状态码这一套换个名字导入，免得同名遮蔽。
from fastapi import status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser, require_platform_admin
from app.core.database import get_session
from app.models.enums import MasterStatus, ProviderStatus
from app.schemas.master_onboarding import (
    OnboardingApplicationItem,
    OnboardingApplicationListResponse,
    ReviewOnboardingRequest,
    ReviewOnboardingResponse,
)
from app.schemas.platform import (
    CreateProviderAdminRequest,
    CreateProviderRequest,
    PlatformProviderItem,
    PlatformProviderListResponse,
    ProviderAdminItem,
    UpdateProviderStatusRequest,
)
from app.services import master_onboarding, platform_provider

__all__ = ["router"]

router = APIRouter(prefix="/api/v1/platform", tags=["platform"])


@router.get(
    "/providers",
    response_model=PlatformProviderListResponse,
    summary="服务商列表（平台侧，分页）",
)
async def list_platform_providers(
    status: ProviderStatus | None = Query(
        None,
        description="按状态过滤，不传=全部",
    ),
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    limit: int = Query(
        platform_provider.DEFAULT_PAGE_LIMIT,
        ge=1,
        description="每页条数，默认 20，上限 100（超过按 100 算）",
    ),
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(require_platform_admin),
) -> PlatformProviderListResponse:
    """列出平台侧可见的全部服务商。"""
    providers, total = await platform_provider.list_providers(
        session,
        status=status,
        page=page,
        limit=limit,
    )
    return PlatformProviderListResponse(
        items=[
            PlatformProviderItem(
                id=provider.id,
                name=provider.name,
                contact_phone=provider.contact_phone,
                commission_rate=provider.commission_rate,
                status=provider.status,
                created_at=provider.created_at,
            )
            for provider in providers
        ],
        total=total,
        page=max(page, 1),
        # 回显实际生效的分页参数：limit 超过上限时这里是被收敛后的值
        limit=min(max(limit, 1), platform_provider.MAX_PAGE_LIMIT),
    )


@router.post(
    "/providers",
    response_model=PlatformProviderItem,
    status_code=http_status.HTTP_201_CREATED,
    summary="新建服务商（初始状态：待审核）",
)
async def create_platform_provider(
    payload: CreateProviderRequest,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(require_platform_admin),
) -> PlatformProviderItem:
    """建一个服务商，初始状态是「待审核」（PENDING）。

    状态**不由请求体决定**：新建一律待审核，要审核通过再调改状态接口。
    """
    provider = await platform_provider.create_provider(
        session,
        name=payload.name,
        contact_phone=payload.contact_phone,
        commission_rate=payload.commission_rate,
        current_user=current_user,
    )
    return PlatformProviderItem(
        id=provider.id,
        name=provider.name,
        contact_phone=provider.contact_phone,
        commission_rate=provider.commission_rate,
        status=provider.status,
        created_at=provider.created_at,
    )


@router.patch(
    "/providers/{provider_id}",
    response_model=PlatformProviderItem,
    summary="改服务商状态（审核通过 / 冻结 / 解冻）",
)
async def update_platform_provider_status(
    provider_id: Annotated[int, Path(ge=1, description="服务商 ID")],
    payload: UpdateProviderStatusRequest,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(require_platform_admin),
) -> PlatformProviderItem:
    """把服务商改成指定状态。

    当前状态不允许这次流转 -> 409（条件 UPDATE 没命中）。
    服务商不存在 -> 404。
    """
    provider = await platform_provider.update_provider_status(
        session,
        provider_id=provider_id,
        status=payload.status,
        current_user=current_user,
    )
    return PlatformProviderItem(
        id=provider.id,
        name=provider.name,
        contact_phone=provider.contact_phone,
        commission_rate=provider.commission_rate,
        status=provider.status,
        created_at=provider.created_at,
    )


@router.post(
    "/providers/{provider_id}/admin",
    response_model=ProviderAdminItem,
    status_code=http_status.HTTP_201_CREATED,
    summary="给服务商建管理员账号",
)
async def create_platform_provider_admin(
    provider_id: Annotated[int, Path(ge=1, description="服务商 ID")],
    payload: CreateProviderAdminRequest,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(require_platform_admin),
) -> ProviderAdminItem:
    """给某个服务商建一个 PROVIDER_ADMIN 账号（入参只有手机号）。

    手机号已被占用 -> 409「手机号已注册」。
    """
    admin = await platform_provider.create_provider_admin(
        session,
        provider_id=provider_id,
        phone=payload.phone,
        current_user=current_user,
    )
    return ProviderAdminItem(
        id=admin.id,
        phone=admin.phone,
        role=admin.role,
        provider_id=admin.provider_id,
        created_at=admin.created_at,
    )


# ==============================================================
# 师傅入驻审核（T-13）
#
# 与上面的服务商管理同一套鉴权：只有 PLATFORM_ADMIN 能审核。
# 审核对象是「师傅」（master），不是「服务商」——路径里那个 id
# 是师傅 ID，别与 provider_id 混淆。
# ==============================================================


@router.get(
    "/masters",
    response_model=OnboardingApplicationListResponse,
    summary="入驻申请列表（平台侧，分页）",
)
async def list_onboarding_applications(
    status: MasterStatus | None = Query(
        None,
        description="按状态过滤，不传=全部（前端一般传 PENDING）",
    ),
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    limit: int = Query(
        master_onboarding.DEFAULT_PAGE_LIMIT,
        ge=1,
        description="每页条数，默认 20，上限 100（超过按 100 算）",
    ),
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(require_platform_admin),
) -> OnboardingApplicationListResponse:
    """列出师傅入驻申请（平台侧）。

    不传 status 就是全部（含已入职的师傅）；审核页一般只看 PENDING。
    """
    applications, total = await master_onboarding.list_onboarding_applications(
        session,
        status=status,
        page=page,
        limit=limit,
    )
    return OnboardingApplicationListResponse(
        items=[
            OnboardingApplicationItem(
                id=application.id,
                real_name=application.real_name,
                phone=application.phone,
                status=application.status,
                provider_id=application.provider_id,
                provider_name=application.provider_name,
                created_at=application.created_at,
            )
            for application in applications
        ],
        total=total,
        page=max(page, 1),
        # 回显实际生效的分页参数：limit 超过上限时这里是被收敛后的值
        limit=min(max(limit, 1), master_onboarding.MAX_PAGE_LIMIT),
    )


@router.post(
    "/masters/{master_id}/review",
    response_model=ReviewOnboardingResponse,
    summary="审核师傅入驻申请（通过 / 驳回）",
)
async def review_onboarding(
    master_id: Annotated[int, Path(ge=1, description="师傅 ID")],
    payload: ReviewOnboardingRequest,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(require_platform_admin),
) -> ReviewOnboardingResponse:
    """审核一份入驻申请。

    通过 -> 师傅状态转「已入驻」（ACTIVE），可选改判到另一家服务商；
    驳回 -> 这一行删掉（没通过审核 = 没入职），账号角色回退成普通用户。

    申请不存在 / 已经不是「待审核」-> 404（两种情况同构）。
    """
    reviewed = await master_onboarding.review_onboarding(
        session,
        current_user=current_user,
        master_id=master_id,
        decision=payload.decision,
        target_provider_id=payload.target_provider_id,
        reason=payload.reason,
    )
    return ReviewOnboardingResponse(
        id=reviewed.id,
        real_name=reviewed.real_name,
        status=reviewed.status,
        provider_id=reviewed.provider_id,
        provider_name=reviewed.provider_name,
        created_at=reviewed.created_at,
    )
