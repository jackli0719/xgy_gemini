"""FastAPI 应用入口。

只做装配：挂路由、注册异常映射。业务逻辑在 service / domain 层。
"""
from __future__ import annotations

from fastapi import FastAPI

from app.api.v1.addresses import router as addresses_router
from app.api.v1.auth import router as auth_router
from app.api.v1.catalog import router as catalog_router
from app.api.v1.dispatch import router as dispatch_router
from app.api.v1.errors import (
    catalog_error_handler,
    dispatch_error_handler,
    master_action_error_handler,
    master_onboarding_error_handler,
    master_query_error_handler,
    place_order_error_handler,
    platform_catalog_error_handler,
    platform_provider_error_handler,
    service_flow_error_handler,
    settlement_error_handler,
)
from app.api.v1.master import router as master_router
from app.api.v1.master_action import router as master_action_router
from app.api.v1.master_onboarding import router as master_onboarding_router
from app.api.v1.orders import router as orders_router
from app.api.v1.pay import router as pay_router
from app.api.v1.platform import router as platform_router
from app.api.v1.platform_catalog import router as platform_catalog_router
from app.api.v1.platform_orders import router as platform_orders_router
from app.api.v1.platform_settlements import router as platform_settlements_router
from app.api.v1.provider import router as provider_router
from app.api.v1.settlements import router as settlements_router
from app.domain.slot_rule import SlotError
from app.services.errors import (
    CatalogError,
    DispatchError,
    MasterActionError,
    MasterOnboardingError,
    MasterQueryError,
    PlaceOrderError,
    PlatformCatalogError,
    PlatformProviderError,
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
app.include_router(catalog_router)
app.include_router(addresses_router)
# 服务商侧只读查询（待派单列表 / 本商师傅列表）
app.include_router(provider_router)
# 师傅端只读查询（我的订单列表 / 订单详情 / 我的资料）
app.include_router(master_router)
# 师傅入驻（登记申请 / 我的申请状态 / 可加入的服务商）
app.include_router(master_onboarding_router)
# 平台侧服务商管理（服务商列表 / 建档 / 改状态 / 建管理员账号）
app.include_router(platform_router)
# 平台侧订单总览（全量订单，可按状态 / 服务商筛选）
app.include_router(platform_orders_router)
# 平台侧目录管理（品类树 / 服务项 / 改价）
app.include_router(platform_catalog_router)
# 平台侧结算单列表（平台财务与平台管理员都能看；只有确认结算限财务）
app.include_router(platform_settlements_router)
# 登录是唯一不需要 token 的业务接口（它本身就是拿 token 的入口）
app.include_router(auth_router)

# 异常映射：service / domain 的业务异常 -> HTTP 状态码。
# 注册在两个基类上，子类按 MRO 自动命中（OrderNoConflictError 命中 503，
# 而不是兜底的 400）。PricingError 不在这两棵树上，保持原样冒泡成 500。
app.add_exception_handler(PlaceOrderError, place_order_error_handler)
app.add_exception_handler(SlotError, place_order_error_handler)
# 派单是另一棵异常树（DispatchError），单独注册自己的兜底文案
app.add_exception_handler(DispatchError, dispatch_error_handler)
# 师傅接单/拒单是第三棵异常树（MasterActionError）
app.add_exception_handler(MasterActionError, master_action_error_handler)
# 师傅端查询是我的订单 / 我的资料，是第七棵异常树（MasterQueryError）
app.add_exception_handler(MasterQueryError, master_query_error_handler)
# 服务流转（开工 / 完工 / 确认完成）是第四棵异常树（ServiceFlowError）
app.add_exception_handler(ServiceFlowError, service_flow_error_handler)
# 结算确认是第五棵异常树（SettlementError）
app.add_exception_handler(SettlementError, settlement_error_handler)
# 目录查询（品类 / 服务项 / 时段）是第六棵异常树（CatalogError）
app.add_exception_handler(CatalogError, catalog_error_handler)
# 平台侧服务商管理是第八棵异常树（PlatformProviderError）
app.add_exception_handler(PlatformProviderError, platform_provider_error_handler)
# 平台侧目录管理（品类 / 服务项 / 改价）是第九棵异常树（PlatformCatalogError）
app.add_exception_handler(PlatformCatalogError, platform_catalog_error_handler)
# 师傅入驻（登记 / 审核）是第十棵异常树（MasterOnboardingError）
app.add_exception_handler(MasterOnboardingError, master_onboarding_error_handler)
