"""师傅接单 / 拒单路由。

接口层只做三件事：校验入参、鉴权、把 service 异常翻译成 HTTP。
业务判断全在 service 里，这里不重复一遍。

**师傅身份来自 token，不来自请求体**：``get_current_user`` 解出当前账号后，
service 按 ``current_user.user_id`` 查 master 表得到师傅身份。
请求体里出现 master_id 会被 schema 422 掉。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser, get_current_user
from app.core.database import get_session
from app.schemas.master_action import AcceptResult, RejectRequest, RejectResult
from app.services.master_action import accept_order as accept_order_service
from app.services.master_action import reject_order as reject_order_service

__all__ = ["router"]

router = APIRouter(prefix="/api/v1/orders", tags=["master-action"])


@router.post(
    "/{order_no}/accept",
    response_model=AcceptResult,
    status_code=status.HTTP_200_OK,
    summary="师傅接单",
)
async def accept_order(
    order_no: str,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
) -> AcceptResult:
    """接下派给自己的订单，订单转为「已接单」。"""
    order = await accept_order_service(
        session,
        order_no=order_no,
        current_user=current_user,
    )
    return AcceptResult(
        order_no=order.order_no,
        status=order.status,
        master_id=order.master_id,
    )


@router.post(
    "/{order_no}/reject",
    response_model=RejectResult,
    status_code=status.HTTP_200_OK,
    summary="师傅拒单",
)
async def reject_order(
    order_no: str,
    payload: RejectRequest,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
) -> RejectResult:
    """拒掉派给自己的订单，订单退回「待派单」，清空承接师傅。"""
    order = await reject_order_service(
        session,
        order_no=order_no,
        reason=payload.reason,
        current_user=current_user,
    )
    return RejectResult(
        order_no=order.order_no,
        status=order.status,
        master_id=order.master_id,
    )
