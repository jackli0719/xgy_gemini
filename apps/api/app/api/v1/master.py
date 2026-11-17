"""师傅端路由（我的订单列表 / 订单详情 / 我的资料）。

接口层只做三件事：校验入参、鉴权、把 service 的结果翻译成 HTTP。
业务判断全在 service 里，这里不重复一遍。

**师傅身份来自 token，不来自请求**（R1）：``require_master_scope``
保证当前账号是 MASTER 角色，service 再按 ``current_user.user_id``
查 master 表得到师傅身份。接口签名里**没有 master_id / user_id /
provider_id 参数**——不是「约定别传」，是「传不进来」。

普通用户 / 服务商账号调这几个接口 -> 403 Forbidden，
文案与别处的越权失败一致（不区分「角色不对」还是「没有师傅身份」）。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser, require_master_scope
from app.core.database import get_session
from app.models.enums import MasterOrderStatus
from app.schemas.master import (
    MasterOrderDetail,
    MasterOrderItem,
    MasterOrderListResponse,
    MasterProfile,
)
from app.services import master_queries

__all__ = ["router"]

router = APIRouter(prefix="/api/v1/master", tags=["master"])


@router.get(
    "/orders",
    response_model=MasterOrderListResponse,
    summary="我的订单列表（按状态）",
)
async def list_master_orders(
    status: MasterOrderStatus = Query(
        MasterOrderStatus.PENDING_ACCEPT,
        description=(
            "按订单状态过滤，只接受师傅端的三种："
            "PENDING_ACCEPT（待接单）/ ACCEPTED（已接单待开工）/ IN_SERVICE（服务中）"
        ),
    ),
    limit: int = Query(
        master_queries.DEFAULT_PAGE_LIMIT,
        ge=1,
        description="每页条数，默认 20，上限 100（超过按 100 算）",
    ),
    offset: int = Query(0, ge=0, description="跳过的条数，默认 0"),
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(require_master_scope),
) -> MasterOrderListResponse:
    """列出派给我的、处于指定状态的订单。

    归属由 token 决定（服务端按 user_id 查 master 表），
    这里不接收 master_id 入参。
    """
    identity = await master_queries.resolve_master(session, current_user)
    rows, total = await master_queries.list_master_orders(
        session,
        master_id=identity.id,
        status=status,
        limit=limit,
        offset=offset,
    )
    return MasterOrderListResponse(
        items=[
            MasterOrderItem(
                order_no=row.order_no,
                status=row.status,
                amount=row.amount,
                item_id=row.item_id,
                item_name=row.item_name,
                slot_date=row.slot_date,
                slot_start_time=row.slot_start_time,
                slot_end_time=row.slot_end_time,
                created_at=row.created_at,
            )
            for row in rows
        ],
        total=total,
        # 回显实际生效的分页参数：limit 超过上限时这里是被收敛后的值
        limit=min(max(limit, 1), master_queries.MAX_PAGE_LIMIT),
        offset=offset,
    )


@router.get(
    "/orders/{order_no}",
    response_model=MasterOrderDetail,
    summary="订单详情",
)
async def get_master_order(
    order_no: str = Path(..., min_length=1, max_length=32, description="订单号"),
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(require_master_scope),
) -> MasterOrderDetail:
    """返回派给我的一笔订单详情（含客户联系方式与上门地址）。

    订单不存在或不是派给我的 -> 404（两种情况同构）。
    """
    identity = await master_queries.resolve_master(session, current_user)
    row = await master_queries.get_master_order(
        session, master_id=identity.id, order_no=order_no
    )
    return MasterOrderDetail(
        id=row.id,
        order_no=row.order_no,
        status=row.status,
        amount=row.amount,
        item_id=row.item_id,
        item_name=row.item_name,
        slot_id=row.slot_id,
        slot_date=row.slot_date,
        slot_start_time=row.slot_start_time,
        slot_end_time=row.slot_end_time,
        created_at=row.created_at,
        customer_contact=row.customer_contact,
        customer_phone=row.customer_phone,
        address_region=row.address_region,
        address_detail=row.address_detail,
        completed_at=row.completed_at,
    )


@router.get(
    "/profile",
    response_model=MasterProfile,
    summary="我的资料",
)
async def get_master_profile(
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(require_master_scope),
) -> MasterProfile:
    """返回当前师傅的资料（姓名 / 评分 / 状态 / 所属服务商）。"""
    identity = await master_queries.resolve_master(session, current_user)
    row = await master_queries.get_master_profile(session, master_id=identity.id)
    return MasterProfile(
        real_name=row.real_name,
        rating=row.rating,
        status=row.status,
        provider_name=row.provider_name,
    )
