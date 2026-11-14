"""mock 支付回调路由。

这是**开发环境专用**的假接口：模拟第三方支付平台的异步回调，
用来在没有真实支付渠道的情况下把订单推进到「待派单」。

环境开关放在 router 层而不是 config 层：
- config 层只负责「应用跑在什么环境」这一件事（``settings.app_env``），
  是个不带业务判断的取值容器；
- 「哪些接口在哪些环境开放」是接口自身的准入策略，跟着它要保护的接口走。
  放在 config 里会变成一个全局开关，日后想按接口分别开关就得再加一堆配置项。

判断放在调用 service **之前**：非 dev 环境下请求根本不该触达业务逻辑，
更不该开事务。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_session
from app.schemas.pay import MockPayNotifyRequest, MockPayResult
from app.services.pay_mock import mock_pay_success

__all__ = ["router"]

router = APIRouter(prefix="/api/v1", tags=["pay"])

# 非 dev 环境下的拒绝文案
MOCK_DISABLED_DETAIL = "mock endpoint disabled in non-dev"

# 只有这个环境值开放 mock 接口
MOCK_ENABLED_ENV = "dev"


@router.post(
    "/pay/mock-notify",
    response_model=MockPayResult,
    status_code=status.HTTP_200_OK,
    summary="mock 支付回调（仅 dev）",
)
async def mock_pay_notify(
    payload: MockPayNotifyRequest,
    session: AsyncSession = Depends(get_session),
) -> MockPayResult:
    """模拟支付成功回调，把订单推进到待派单。

    幂等：重复回调同一笔订单不会重复改状态、重复写状态流转日志。
    """
    if not _mock_enabled():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=MOCK_DISABLED_DETAIL,
        )

    order = await mock_pay_success(session, order_no=payload.order_no)
    return MockPayResult(
        order_no=order.order_no,
        status=order.status,
        pay_status=order.pay_status,
    )


def _mock_enabled() -> bool:
    """当前环境是否开放 mock 接口。"""
    return settings.app_env.strip().lower() == MOCK_ENABLED_ENV
