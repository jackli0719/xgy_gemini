"""下单路由。

接口层只做三件事：校验入参、鉴权、把 service 异常翻译成 HTTP。
业务判断全在 service 与 domain 里，这里不重复一遍。

下单人的身份只从 token 来（``current_user.user_id``），
请求体里出现 user_id 会被 schema 直接 422 掉。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser, get_current_user
from app.core.database import get_session
from app.schemas.order import OrderSummary, PlaceOrderRequest
from app.services.place_order import place_order

__all__ = ["router"]

router = APIRouter(prefix="/api/v1", tags=["orders"])


@router.post(
    "/orders",
    response_model=OrderSummary,
    status_code=status.HTTP_201_CREATED,
    summary="下单",
)
async def create_order(
    payload: PlaceOrderRequest,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
) -> OrderSummary:
    """创建一笔订单，返回订单摘要。"""
    order = await place_order(
        session,
        user_id=current_user.user_id,
        item_id=payload.item_id,
        slot_id=payload.slot_id,
        address_id=payload.address_id,
    )
    # 只回摘要：provider_id / master_id 是内部派单信息，完整地址是个人数据
    return OrderSummary(
        id=order.id,
        order_no=order.order_no,
        status=order.status,
        amount=order.amount,
    )
