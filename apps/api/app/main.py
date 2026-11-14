"""FastAPI 应用入口。

只做装配：挂路由、注册异常映射。业务逻辑在 service / domain 层。
"""
from __future__ import annotations

from fastapi import FastAPI

from app.api.v1.dispatch import router as dispatch_router
from app.api.v1.errors import (
    dispatch_error_handler,
    master_action_error_handler,
    place_order_error_handler,
    service_flow_error_handler,
    settlement_error_handler,
)
from app.api.v1.master_action import router as master_action_router
from app.api.v1.orders import router as orders_router
from app.api.v1.pay import router as pay_router
from app.api.v1.settlements import router as settlements_router
from app.domain.slot_rule import SlotError
from app.services.errors import (
    DispatchError,
    MasterActionError,
    PlaceOrderError,
    ServiceFlowError,
    SettlementError,
)

__all__ = ["app"]

app = FastAPI(
    title="OTO 家政服务平台 API",
    version="0.1.0",
)

app.include_router(orders_router)
app.include_router(pay_router)
app.include_router(dispatch_router)
app.include_router(master_action_router)
app.include_router(settlements_router)

# 异常映射：service / domain 的业务异常 -> HTTP 状态码。
# 注册在两个基类上，子类按 MRO 自动命中（OrderNoConflictError 命中 503，
# 而不是兜底的 400）。PricingError 不在这两棵树上，保持原样冒泡成 500。
app.add_exception_handler(PlaceOrderError, place_order_error_handler)
app.add_exception_handler(SlotError, place_order_error_handler)
# 派单是另一棵异常树（DispatchError），单独注册自己的兜底文案
app.add_exception_handler(DispatchError, dispatch_error_handler)
# 师傅接单/拒单是第三棵异常树（MasterActionError）
app.add_exception_handler(MasterActionError, master_action_error_handler)
# 服务流转（开工 / 完工 / 确认完成）是第四棵异常树（ServiceFlowError）
app.add_exception_handler(ServiceFlowError, service_flow_error_handler)
# 结算确认是第五棵异常树（SettlementError）
app.add_exception_handler(SettlementError, settlement_error_handler)
