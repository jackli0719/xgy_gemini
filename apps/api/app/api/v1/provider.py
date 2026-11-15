"""服务商侧路由（待派单列表 / 本商师傅列表 / 改师傅状态）。

接口层只做三件事：校验入参、鉴权、把 service 的结果翻译成 HTTP。
业务判断全在 service 里，这里不重复一遍。

**服务商归属来自 token，不来自请求**（R1）：``require_provider_scope``
保证当前账号是服务商侧角色且带着 provider_id，service 直接拿
``current_user.provider_id`` 过滤。接口签名里**没有 provider_id 参数**——
不是「约定别传」，是「传不进来」。

普通用户（角色 USER / MASTER）调这几个接口 -> 403 Forbidden，
文案与别处的越权失败一致（不区分「角色不对」还是「没有归属」）。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import FORBIDDEN_DETAIL, CurrentUser, require_provider_scope
from app.core.database import get_session
from app.models.enums import OrderStatus
from app.schemas.provider import (
    ProviderMasterItem,
    ProviderMasterListResponse,
    ProviderOrderItem,
    ProviderOrderListResponse,
    UpdateMasterStatusRequest,
)
from app.services import master_management, provider_queries

__all__ = ["router"]

router = APIRouter(prefix="/api/v1/provider", tags=["provider"])


@router.get(
    "/orders",
    response_model=ProviderOrderListResponse,
    summary="本商订单列表（默认待派单）",
)
async def list_provider_orders(
    status: OrderStatus = Query(
        OrderStatus.PENDING_DISPATCH,
        description="按订单状态过滤，默认待派单（PENDING_DISPATCH）",
    ),
    limit: int = Query(
        provider_queries.DEFAULT_PAGE_LIMIT,
        ge=1,
        description="每页条数，默认 20，上限 100（超过按 100 算）",
    ),
    offset: int = Query(0, ge=0, description="跳过的条数，默认 0"),
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(require_provider_scope),
) -> ProviderOrderListResponse:
    """列出本商可见的、处于指定状态的订单。

    待派单（PENDING_DISPATCH）时，可见范围 = 公共待派单池（还没归属的单）
    + 本商专属（师傅拒单后退回本商的单）。可见范围与「能不能派」
    是同一套条件（见 app.services.provider_queries）。
    """
    provider_id = _provider_id_of(current_user)
    rows, total = await provider_queries.list_provider_orders(
        session,
        provider_id=provider_id,
        status=status,
        limit=limit,
        offset=offset,
    )
    return ProviderOrderListResponse(
        items=[
            ProviderOrderItem(
                id=row.id,
                order_no=row.order_no,
                status=row.status,
                pay_status=row.pay_status,
                amount=row.amount,
                item_id=row.item_id,
                item_name=row.item_name,
                slot_date=row.slot_date,
                slot_start_time=row.slot_start_time,
                created_at=row.created_at,
            )
            for row in rows
        ],
        total=total,
        # 回显实际生效的分页参数：limit 超过上限时这里是被收敛后的值
        limit=min(max(limit, 1), provider_queries.MAX_PAGE_LIMIT),
        offset=offset,
    )


@router.get(
    "/masters",
    response_model=ProviderMasterListResponse,
    summary="本商师傅列表",
)
async def list_provider_masters(
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(require_provider_scope),
) -> ProviderMasterListResponse:
    """列出本商的师傅（id / 姓名 / 手机号 / 评分 / 状态）。

    所有状态的师傅都返回（含停用 / 休假），由派单的人自己挑。
    """
    provider_id = _provider_id_of(current_user)
    rows = await provider_queries.list_provider_masters(
        session, provider_id=provider_id
    )
    return ProviderMasterListResponse(
        items=[
            ProviderMasterItem(
                id=row.id,
                real_name=row.real_name,
                phone=row.phone,
                rating=row.rating,
                status=row.status,
            )
            for row in rows
        ],
        total=len(rows),
    )


@router.patch(
    "/masters/{master_id}",
    response_model=ProviderMasterItem,
    summary="改本商师傅状态",
)
async def update_provider_master(
    master_id: int,
    payload: UpdateMasterStatusRequest,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(require_provider_scope),
) -> ProviderMasterItem:
    """把本商师傅改成指定状态（启用 / 休假 / 停用）。

    师傅不属于本商，或这个师傅不存在，都是同一个 404、同一句话
    （不泄露存在性）。
    """
    # 归属由 token 决定，这里不接收 provider_id 入参。
    # _provider_id_of 只是把「没有归属」这件事挡在 service 之前，
    # 让它跟别处的越权失败返回同一句话（Forbidden）。
    _provider_id_of(current_user)
    # status 直接把窄枚举（SettableMasterStatus）传下去：
    # 接口层已经把 PENDING 变成 422，service 那边按同一份枚举再挡一次。
    result = await master_management.update_master_status(
        session,
        master_id=master_id,
        status=payload.status,
        current_user=current_user,
    )
    return ProviderMasterItem(
        id=result.id,
        real_name=result.real_name,
        phone=result.phone,
        rating=result.rating,
        status=result.status,
    )


def _provider_id_of(current_user: CurrentUser) -> int:
    """取当前用户的服务商归属。

    ``require_provider_scope`` 已经保证它不是 None；这里的判断只是为了
    让类型收窄成立（provider_id 的类型是 int | None），顺带守住
    「不变量只在依赖里保证」这个单点假设——万一哪天依赖被换掉，
    这里会立刻拒，而不是把 None 传进 service 去查一个空归属。
    """
    provider_id = current_user.provider_id
    if provider_id is None:
        raise HTTPException(status_code=403, detail=FORBIDDEN_DETAIL)
    return provider_id
