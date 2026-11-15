"""平台侧订单总览 service（PLAT-02）。

平台看的是**全量订单**：不按用户过滤，也不按服务商过滤。
这不是「接口忘了加过滤条件」，而是平台侧的特权——它由**角色**决定
（``require_platform_staff``），不是由请求参数决定。

四条硬约束：

1. **身份只从 token 来**：函数签名里没有 operator 参数，
   也不接受 user_id ——平台看全量，靠的是角色，不是客户端自报。
2. **可按状态 / 服务商筛选，但筛选不是隔离**：``status`` /
   ``provider_id`` 是查询条件；不传就是全量。没派的单
   （provider_id 为空）在「不筛选」时也会出现。
3. **只读**：这个模块只 select，不 insert / update / delete。
4. **分页有上限**：limit 收敛到 [1, MAX_PAGE_LIMIT]（上限 100），
   与用户侧 / 服务商侧订单列表同一套口径。

**排序**：created_at 倒序，同一时间用 id 倒序兜底
（created_at 精度有限，同一批插入的订单时间可能完全相同，
没有第二排序键时分页会在两页之间重复或漏掉同一行）。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog import ServiceItem
from app.models.enums import OrderStatus, PayStatus
from app.models.order import Order
from app.models.provider import ServiceProvider

__all__ = [
    "DEFAULT_PAGE_LIMIT",
    "MAX_PAGE_LIMIT",
    "PlatformOrderProviderOption",
    "PlatformOrderRow",
    "list_order_providers",
    "list_platform_orders",
]

# 分页口径与用户侧 / 服务商侧订单列表一致
DEFAULT_PAGE_LIMIT = 20
MAX_PAGE_LIMIT = 100


@dataclass(frozen=True)
class PlatformOrderRow:
    """订单总览里的一笔订单。"""

    id: int
    order_no: str
    status: OrderStatus
    pay_status: PayStatus
    amount: Decimal
    user_id: int
    provider_id: int | None
    provider_name: str | None
    item_id: int
    item_name: str
    created_at: datetime


@dataclass(frozen=True)
class PlatformOrderProviderOption:
    """筛选栏里的一个服务商选项。"""

    id: int
    name: str


async def list_order_providers(
    session: AsyncSession,
) -> list[PlatformOrderProviderOption]:
    """返回「有过订单的服务商」列表（筛选栏的选项）。

    **为什么要单独查**：平台侧的服务商列表接口（/api/v1/platform/providers）
    只对平台管理员开放，而订单总览平台运营也要能筛——所以订单接口自己
    带上筛选选项，不去调那个只有管理员能调的接口。

    只列**有过订单**的服务商：没订单的服务商筛出来一定是空的，
    列出来只是给筛选栏添噪音。

    排序按 id（不按名称）：与别处的列表同一口径，也保证顺序稳定。
    """
    rows = (
        await session.execute(
            select(ServiceProvider.id, ServiceProvider.name)
            .join(Order, Order.provider_id == ServiceProvider.id)
            .distinct()
            .order_by(ServiceProvider.id)
        )
    ).all()
    return [PlatformOrderProviderOption(id=provider_id, name=name) for provider_id, name in rows]


async def list_platform_orders(
    session: AsyncSession,
    *,
    status: OrderStatus | None = None,
    provider_id: int | None = None,
    page: int = 1,
    limit: int = DEFAULT_PAGE_LIMIT,
) -> tuple[list[PlatformOrderRow], int]:
    """返回平台侧可见的订单（一页 + 总数）。

    ``status`` / ``provider_id`` 传 None 表示不按它过滤（平台看全量）。

    服务商名用 **outer join**：还没派的单 provider_id 为空，
    inner join 会把「还没派出去的单」整批漏掉——而那恰恰是
    平台最需要盯的单子。
    """
    page = max(page, 1)
    limit = min(max(limit, 1), MAX_PAGE_LIMIT)

    conditions = []
    if status is not None:
        conditions.append(Order.status == status)
    if provider_id is not None:
        conditions.append(Order.provider_id == provider_id)

    count_stmt = select(func.count()).select_from(Order)
    if conditions:
        count_stmt = count_stmt.where(*conditions)
    total = (await session.execute(count_stmt)).scalar_one()

    stmt = (
        select(
            Order.id,
            Order.order_no,
            Order.status,
            Order.pay_status,
            Order.amount,
            Order.user_id,
            Order.provider_id,
            ServiceProvider.name,
            Order.item_id,
            ServiceItem.name,
            Order.created_at,
        )
        .join(ServiceItem, ServiceItem.id == Order.item_id)
        .outerjoin(ServiceProvider, ServiceProvider.id == Order.provider_id)
    )
    if conditions:
        stmt = stmt.where(*conditions)
    stmt = (
        stmt.order_by(Order.created_at.desc(), Order.id.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    )

    rows = (await session.execute(stmt)).all()
    return [PlatformOrderRow(*row) for row in rows], total
