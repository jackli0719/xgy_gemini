"""师傅入驻路由（登记申请 / 我的申请状态 / 可加入的服务商）。

接口层只做三件事：校验入参、鉴权、把 service 的结果翻译成 HTTP。
业务判断全在 service 里，这里不重复一遍。

**身份来自 token，不来自请求**（R1）：这三个接口只要求「已登录」，
师傅身份由 service 按 ``current_user.user_id`` 查 master 表得到。
接口签名里**没有 user_id / master_id 参数**——不是「约定别传」，
是「传不进来」。

**为什么这一组接口只要求登录、不过 ``require_master_scope``**：
提交申请时这个账号还**不是**师傅（角色是 USER，审核通过后才变成
MASTER）。如果这里就要求师傅身份，师傅永远提交不了申请。

**请求体里没有 provider_id**：师傅填的是 ``target_provider_id``
（申请加入哪家），那是申请内容，归属由平台审核确认——
见 app.schemas.master_onboarding 的说明。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser, get_current_user
from app.core.database import get_session
from app.schemas.master_onboarding import (
    JoinableProviderItem,
    JoinableProviderListResponse,
    OnboardingApplicationItem,
    SubmitOnboardingRequest,
)
from app.services import master_onboarding

__all__ = ["router"]

router = APIRouter(prefix="/api/v1/masters", tags=["master-onboarding"])


@router.get(
    "/joinable-providers",
    response_model=JoinableProviderListResponse,
    summary="可申请加入的服务商列表",
)
async def list_joinable_providers(
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
) -> JoinableProviderListResponse:
    """列出可以申请加入的服务商（只有正常营业的）。

    只暴露 id 与名称：佣金率与联系电话是平台侧 / 服务商侧的信息。
    """
    providers = await master_onboarding.list_joinable_providers(session)
    return JoinableProviderListResponse(
        items=[
            JoinableProviderItem(id=provider.id, name=provider.name)
            for provider in providers
        ]
    )


@router.post(
    "/onboarding",
    response_model=OnboardingApplicationItem,
    summary="提交入驻申请（登记为待审核）",
)
async def submit_onboarding(
    payload: SubmitOnboardingRequest,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
) -> OnboardingApplicationItem:
    """提交入驻申请。

    登记成功状态是「待审核」（PENDING）——能不能入职由平台说了算。
    已经申请过 / 已入职 -> 409；目标服务商不可加入 -> 404。
    """
    submission = await master_onboarding.submit_onboarding(
        session,
        current_user=current_user,
        real_name=payload.real_name,
        target_provider_id=payload.target_provider_id,
    )
    return OnboardingApplicationItem(
        id=submission.master_id,
        real_name=submission.real_name,
        # 手机号是申请人的手机号（就是登录账号那一个）
        phone=submission.phone,
        status=submission.status,
        provider_id=submission.provider_id,
        provider_name=submission.provider_name,
        created_at=submission.created_at,
    )


@router.get(
    "/onboarding",
    response_model=OnboardingApplicationItem,
    summary="我的入驻申请",
)
async def get_my_onboarding(
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
) -> OnboardingApplicationItem:
    """返回当前账号的入驻申请。

    没有申请 -> 404（前端据此显示「去申请」）。
    """
    application = await master_onboarding.get_my_onboarding(
        session, current_user=current_user
    )
    return OnboardingApplicationItem(
        id=application.id,
        real_name=application.real_name,
        phone=application.phone,
        status=application.status,
        provider_id=application.provider_id,
        provider_name=application.provider_name,
        created_at=application.created_at,
    )
