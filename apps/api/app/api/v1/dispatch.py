"""派单路由。

接口层只做三件事：校验入参、鉴权、把 service 异常翻译成 HTTP。
业务判断全在 service 里，这里不重复一遍。

**服务商归属来自 token，不来自请求体**：``require_provider_scope`` 保证
当前账号是服务商侧角色且带着 provider_id，派单 service 直接用
``current_user.provider_id``。请求体里出现 provider_id 会被 schema 422 掉。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser, require_provider_scope
from app.core.database import get_session
from app.schemas.dispatch import DispatchRequest, DispatchResult
from app.services.dispatch import dispatch_order as dispatch_order_service

__all__ = ["router"]

router = APIRouter(prefix="/api/v1/orders", tags=["dispatch"])


@router.post(
    "/{order_id}/dispatch",
    response_model=DispatchResult,
    status_code=status.HTTP_200_OK,
    summary="派单",
)
async def dispatch_order(
    order_id: int,
    payload: DispatchRequest,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(require_provider_scope),
) -> DispatchResult:
    """把订单派给本商师傅，订单转为「待接单」。"""
    order = await dispatch_order_service(
        session,
        order_id=order_id,
        master_id=payload.master_id,
        current_user=current_user,
    )
    return DispatchResult(
        order_no=order.order_no,
        status=order.status,
        master_id=order.master_id,
    )
