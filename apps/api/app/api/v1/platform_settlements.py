"""平台侧结算单列表路由（PLAT-03）。

一个接口：``GET /api/v1/platform/settlements``。

**看与确认是两件事**：

- **看**（这个接口）：平台财务与平台管理员都能看——管理员管全局，
  对账、核查服务商的结算情况是它的日常。
- **确认**（POST /api/v1/settlements/{id}/confirm，T-11b）：只认
  PLATFORM_FINANCE。把钱定下来的动作不外放。

角色不对一律 403，而且是在碰库之前就挡住
（角色不对的账号连「有几张待结算单」都问不到）。

**筛选不是隔离边界**：这两个角色本来就看全平台结算单，
``status`` / ``provider_id`` 只是查询条件。

**分页上限 100**：limit 超过上限按 100 算，不报错
（与用户侧 / 服务商侧 / 平台订单列表同一套口径）。
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser, require_platform_settlement_viewer
from app.core.database import get_session
from app.models.enums import SettlementStatus
from app.schemas.platform_settlement import (
    PlatformSettlementItem,
    PlatformSettlementListResponse,
    PlatformSettlementProviderOption,
)
from app.services import platform_settlements

__all__ = ["router"]

router = APIRouter(prefix="/api/v1/platform", tags=["platform-settlements"])


@router.get(
    "/settlements",
    response_model=PlatformSettlementListResponse,
    summary="平台结算单列表（可按状态 / 服务商筛选）",
)
async def list_platform_settlements(
    status: SettlementStatus | None = Query(
        None,
        description="按结算单状态过滤，不传=全部",
    ),
    provider_id: Annotated[
        int | None, Query(gt=0, description="按服务商过滤，不传=全部")
    ] = None,
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    limit: int = Query(
        platform_settlements.DEFAULT_PAGE_LIMIT,
        ge=1,
        description="每页条数，默认 20，上限 100（超过按 100 算）",
    ),
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(require_platform_settlement_viewer),
) -> PlatformSettlementListResponse:
    """列出平台侧可见的全部结算单（财务与管理员）。"""
    # 分页参数**在这里收敛一次**（全仓库唯一的收敛点），然后把收敛后的值
    # 传给 service。收敛做两遍（接口层 + service 层）的话，两边哪天不一致，
    # 就会出现「回显 limit=100、实际却取回 500 条」这种自相矛盾的响应。
    # service 那边只做断言（收到越界值就抛错），不重复收敛。
    effective_page = max(page, 1)
    effective_limit = min(max(limit, 1), platform_settlements.MAX_PAGE_LIMIT)

    settlements, total = await platform_settlements.list_platform_settlements(
        session,
        status=status,
        provider_id=provider_id,
        page=effective_page,
        limit=effective_limit,
    )
    providers = await platform_settlements.list_settlement_providers(session)
    return PlatformSettlementListResponse(
        items=[
            PlatformSettlementItem(
                id=settlement.id,
                provider_name=settlement.provider_name,
                period_start=settlement.period_start,
                period_end=settlement.period_end,
                total_amount=settlement.total_amount,
                commission_amount=settlement.commission_amount,
                net_amount=settlement.net_amount,
                status=settlement.status,
                confirmed_at=settlement.confirmed_at,
            )
            for settlement in settlements
        ],
        total=total,
        page=effective_page,
        # 回显实际生效的分页参数：limit 超过上限时这里是被收敛后的值
        limit=effective_limit,
        providers=[
            PlatformSettlementProviderOption(id=provider.id, name=provider.name)
            for provider in providers
        ],
    )
