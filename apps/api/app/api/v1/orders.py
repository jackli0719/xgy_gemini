"""下单与服务流转路由。

接口层只做三件事：校验入参、鉴权、把 service 异常翻译成 HTTP。
业务判断全在 service 与 domain 里，这里不重复一遍。

**身份只从 token 来**（``current_user.user_id``）：

- 下单：请求体里出现 user_id 会被 schema 直接 422 掉；
- 开工 / 完工 / 确认完成：三个动作**根本没有请求体**，
  师傅身份由服务端按 token 的 user_id 查 master 表得到，
  客户身份就是 token 里的 user_id。客户端无从自报身份（R1）。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser, get_current_user
from app.core.database import get_session
from app.schemas.order import OrderSummary, PlaceOrderRequest
from app.schemas.service_flow import ServiceFlowResult
from app.services.place_order import place_order
from app.services.service_flow import confirm_complete, finish_service, start_service

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


# =====================================================================
# 服务流转：开工 / 完工 / 客户确认完成
#
# 三个动作都是「推进一笔已有订单的状态」，不是创建资源，所以一律 200
# （与接单 / 拒单一致）。201 留给真正创建出东西的接口（如下单）。
#
# 请求体里没有身份字段：师傅身份由 service 按 token 的 user_id 查 master 表
# 得到，客户身份就是 token 里的 user_id（R1）。
# 异常不用在这里翻译：ServiceFlowError 已在 app.main 里注册了 handler，
# 「订单不存在」走 OrderNotFoundError（404，与下单 / 接单同一条消息）。
# =====================================================================


@router.post(
    "/orders/{order_no}/start",
    response_model=ServiceFlowResult,
    status_code=status.HTTP_200_OK,
    summary="师傅开工",
)
async def start_order_service(
    order_no: str,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
) -> ServiceFlowResult:
    """开工：订单从「已接单」流转到「服务中」。"""
    order = await start_service(session, current=current_user, order_no=order_no)
    return ServiceFlowResult(
        order_no=order.order_no,
        status=order.status,
        completed_at=order.completed_at,
    )


@router.post(
    "/orders/{order_no}/finish",
    response_model=ServiceFlowResult,
    status_code=status.HTTP_200_OK,
    summary="师傅完工",
)
async def finish_order_service(
    order_no: str,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
) -> ServiceFlowResult:
    """完工：订单从「服务中」流转到「待确认」，等客户确认。"""
    order = await finish_service(session, current=current_user, order_no=order_no)
    return ServiceFlowResult(
        order_no=order.order_no,
        status=order.status,
        completed_at=order.completed_at,
    )


@router.post(
    "/orders/{order_no}/confirm",
    response_model=ServiceFlowResult,
    status_code=status.HTTP_200_OK,
    summary="客户确认完成",
)
async def confirm_order_service(
    order_no: str,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
) -> ServiceFlowResult:
    """客户确认完成：订单从「待确认」流转到「已完成」，并写入完工时间。"""
    order = await confirm_complete(session, current=current_user, order_no=order_no)
    return ServiceFlowResult(
        order_no=order.order_no,
        status=order.status,
        completed_at=order.completed_at,
    )
