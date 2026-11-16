"""结算确认路由。

接口层只做三件事：校验入参、鉴权、把 service 异常翻译成 HTTP。
业务判断全在 service 里，这里不重复一遍。

**鉴权放在路由层**（``require_platform_finance``）：确认结算是把钱
定下来的动作，只有平台财务能做。依赖在**碰库之前**就把角色不对的
账号挡掉——它们连「有几张待结算单」都问不到。

service 里还有一道同样的守卫（``app.services.settle._require_finance_role``），
那是**纵深防御**：service 可能被别处直接调用（定时任务、内部脚本），
不依赖路由层替它把关。

**结算单 id 从路径取，确认人从 token 取**：请求体里没有任何身份字段，
客户端不能自报「我替谁确认」（R1）。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser, require_platform_finance
from app.core.database import get_session
from app.schemas.settlement import ConfirmSettlementResult
from app.services.settle import confirm_settlement as confirm_settlement_service

__all__ = ["router"]

router = APIRouter(prefix="/api/v1/settlements", tags=["settlements"])


@router.post(
    "/{settlement_id}/confirm",
    response_model=ConfirmSettlementResult,
    status_code=status.HTTP_200_OK,
    summary="财务确认结算",
)
async def confirm_settlement(
    settlement_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(require_platform_finance),
) -> ConfirmSettlementResult:
    """确认一张待结算的结算单，关联订单一并转为「已结算」。

    角色不对返回 403；结算单不存在或已被确认返回 404（两种情况同构）。

    **只有平台财务能确认**（``require_platform_finance``）：
    路由层就在碰库之前把别的角色挡掉（管理员能看结算单列表，
    但看得到不等于确认得了）。
    """
    settlement = await confirm_settlement_service(
        session,
        current=current_user,
        settlement_id=settlement_id,
    )
    return ConfirmSettlementResult(
        id=settlement.id,
        status=settlement.status,
        net_amount=settlement.net_amount,
        confirmed_at=settlement.confirmed_at,
    )
