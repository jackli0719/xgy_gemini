"""平台侧订单总览路由（PLAT-02）。

一个接口：``GET /api/v1/platform/orders``。

**为什么平台看得到全量订单**：这是平台侧的特权，来自**角色**
（``require_platform_staff``），不是来自请求参数。所以接口里
没有 user_id 这种东西——请求体 / 查询参数里出现 user_id 会被 schema
直接 422（平台想看哪家的单，用 provider_id 筛，不是替用户挑身份）。

**分页上限 100**：limit 超过上限按 100 算，不报错
（与用户侧 / 服务商侧订单列表同一套口径，见
app.services.platform_orders）。
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser, require_platform_staff
from app.core.database import get_session
from app.models.enums import OrderStatus
from app.schemas.platform_order import (
    PlatformOrderItem,
    PlatformOrderListResponse,
    PlatformOrderProviderOption,
)
from app.services import platform_orders

__all__ = ["router"]

router = APIRouter(prefix="/api/v1/platform", tags=["platform-orders"])


@router.get(
    "/orders",
    response_model=PlatformOrderListResponse,
    summary="平台订单总览（全量，可按状态 / 服务商筛选）",
)
async def list_platform_orders(
    status: OrderStatus | None = Query(
        None,
        description="按订单状态过滤，不传=全部",
    ),
    provider_id: Annotated[int | None, Query(gt=0, description="按服务商过滤，不传=全部")] = None,
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    limit: int = Query(
        platform_orders.DEFAULT_PAGE_LIMIT,
        ge=1,
        description="每页条数，默认 20，上限 100（超过按 100 算）",
    ),
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(require_platform_staff),
) -> PlatformOrderListResponse:
    """列出平台侧可见的全部订单。

    **不带 user_id 过滤**：平台看的是全量订单。
    """
    orders, total = await platform_orders.list_platform_orders(
        session,
        status=status,
        provider_id=provider_id,
        page=page,
        limit=limit,
    )
    providers = await platform_orders.list_order_providers(session)
    return PlatformOrderListResponse(
        items=[
            PlatformOrderItem(
                id=order.id,
                order_no=order.order_no,
                status=order.status,
                pay_status=order.pay_status,
                amount=order.amount,
                user_id=order.user_id,
                provider_id=order.provider_id,
                provider_name=order.provider_name,
                item_id=order.item_id,
                item_name=order.item_name,
                created_at=order.created_at,
            )
            for order in orders
        ],
        total=total,
        page=max(page, 1),
        # 回显实际生效的分页参数：limit 超过上限时这里是被收敛后的值
        limit=min(max(limit, 1), platform_orders.MAX_PAGE_LIMIT),
        providers=[
            PlatformOrderProviderOption(id=provider.id, name=provider.name)
            for provider in providers
        ],
    )
