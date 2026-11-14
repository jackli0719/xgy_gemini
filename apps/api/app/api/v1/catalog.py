"""目录查询路由：品类树、品类下的服务项、服务项的可预约时段。

三个接口都是**只读**的，接口层只做三件事：鉴权、收查询参数、
把 service 的结果翻译成响应模型。业务判断全在 service 里。

**身份只从 token 来**（R5）：这三个接口本来就不按用户过滤数据
（品类和服务项对所有用户是一样的），但仍然要求登录——
用户侧 App 的接口都在登录之后，混进一个不需要 token 的接口
会让鉴权边界变得含糊（「这个接口为什么不要 token？」）。

品类不存在 / 已停用 -> 404；服务项不存在 / 已停用 -> 404。
两种情况的文案各自一致，不泄露状态。
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser, get_current_user
from app.core.database import get_session
from app.schemas.catalog import (
    CategoryNode,
    ServiceItemSummary,
    SlotAvailability,
)
from app.services import user_queries

__all__ = ["router"]

router = APIRouter(prefix="/api/v1", tags=["catalog"])


def _to_category_node(row: user_queries.CategoryRow) -> CategoryNode:
    """service 的品类行 -> 响应模型（子树递归转换）。"""
    return CategoryNode(
        id=row.id,
        name=row.name,
        parent_id=row.parent_id,
        sort_order=row.sort_order,
        children=[_to_category_node(child) for child in row.children],
    )


@router.get(
    "/catalog",
    response_model=list[CategoryNode],
    summary="品类列表（含子品类）",
)
async def list_categories(
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
) -> list[CategoryNode]:
    """返回品类树：一级品类，每个带自己的子树。

    只返回启用的品类；父品类停用时整棵子树一起下架。
    """
    rows = await user_queries.list_categories(session)
    return [_to_category_node(row) for row in rows]


@router.get(
    "/catalog/{category_id}/items",
    response_model=list[ServiceItemSummary],
    summary="某品类下的服务项",
)
async def list_category_items(
    category_id: int = Path(..., gt=0, description="品类 ID"),
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
) -> list[ServiceItemSummary]:
    """返回某个品类下**直接归属**该品类的服务项（只含启用的）。

    子品类下的服务项不在这里返回——前端拿到品类树后自己按 category_id 再查。
    """
    rows = await user_queries.list_category_items(session, category_id=category_id)
    return [
        ServiceItemSummary(
            id=row.id,
            category_id=row.category_id,
            name=row.name,
            base_price=row.base_price,
            duration_min=row.duration_min,
        )
        for row in rows
    ]


@router.get(
    "/items/{item_id}/slots",
    response_model=list[SlotAvailability],
    summary="某服务项某天的可预约时段",
)
async def list_item_slots(
    item_id: int = Path(..., gt=0, description="服务项 ID"),
    on_date: date = Query(..., alias="date", description="查询日期，YYYY-MM-DD"),
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
) -> list[SlotAvailability]:
    """返回某服务项在某天的可预约时段。

    只返回还能约的：日期 >= 今天，且 available = capacity - used > 0。
    已约满的时段不出现在列表里（点进去也会被下单接口挡成 409）。
    """
    rows = await user_queries.list_item_slots(session, item_id=item_id, on_date=on_date)
    return [
        SlotAvailability(
            id=row.id,
            item_id=row.item_id,
            date=row.date,
            start_time=row.start_time,
            end_time=row.end_time,
            capacity=row.capacity,
            used=row.used,
            available=row.available,
        )
        for row in rows
    ]
