"""平台侧结算单列表 service（PLAT-03）。

平台侧（财务 / 管理员）在这里看全平台的结算单：哪些还等着确认
（``PENDING``）、哪些已经确认过（``CONFIRMED``），以及每个周期的金额三件套。

四条硬约束：

1. **只读**：这个模块只 select，不 insert / update / delete。
   确认结算是另一个动作（``app.services.settle.confirm_settlement``），
   两条路径不混——列表接口永远不写库。
2. **身份只从 token 来**：函数签名里没有 operator 参数，
   也不接受 user_id ——看到的是全平台结算单，靠的是**角色**
   （``require_platform_settlement_viewer``），不是客户端自报。
3. **筛选是查询条件，不是隔离边界**：``status`` / ``provider_id``
   不传就是全量。平台侧角色本来就能看全部结算单，所以这里没有
   「只能看自己家」这种约束。
4. **分页有上限**：limit 收敛到 [1, MAX_PAGE_LIMIT]（上限 100），
   与用户侧 / 服务商侧 / 平台订单列表同一套口径。

**金额口径**与服务商侧完全一致（见 app/models/settlement.py）：
``total_amount``（客户实付合计）= ``commission_amount``（平台佣金）
+ ``net_amount``（服务商实收）。

**排序**：id 倒序（最新的结算单在最前面）。结算单没有「下单时间」，
按 id 倒序等价于按创建时间倒序，而且稳定——同一批生成的多张单
不会在两页之间重复或漏掉。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import SettlementStatus
from app.models.provider import ServiceProvider
from app.models.settlement import Settlement

__all__ = [
    "DEFAULT_PAGE_LIMIT",
    "MAX_PAGE_LIMIT",
    "PlatformSettlementProviderOption",
    "PlatformSettlementRow",
    "list_settlement_providers",
    "list_platform_settlements",
]

# 分页口径与用户侧 / 服务商侧 / 平台订单列表一致
DEFAULT_PAGE_LIMIT = 20
MAX_PAGE_LIMIT = 100


@dataclass(frozen=True)
class PlatformSettlementRow:
    """列表里的一张结算单。

    **只有要给人看的字段**：没有 confirmed_by（确认人 id）、
    没有 created_at / updated_at（内部时间戳）、没有 commission_rate
    （费率是服务商的属性，不是这张单的属性）。内部字段不进接口。
    """

    id: int
    provider_name: str
    period_start: date
    period_end: date
    total_amount: Decimal
    commission_amount: Decimal
    net_amount: Decimal
    status: SettlementStatus
    confirmed_at: datetime | None


@dataclass(frozen=True)
class PlatformSettlementProviderOption:
    """筛选栏里的一个服务商选项。"""

    id: int
    name: str


async def list_platform_settlements(
    session: AsyncSession,
    *,
    status: SettlementStatus | None = None,
    provider_id: int | None = None,
    page: int = 1,
    limit: int = DEFAULT_PAGE_LIMIT,
) -> tuple[list[PlatformSettlementRow], int]:
    """返回平台侧可见的结算单（一页 + 总数）。

    ``status`` / ``provider_id`` 传 None 表示不按它过滤（平台侧看全量）。
    """
    page = max(page, 1)
    limit = min(max(limit, 1), MAX_PAGE_LIMIT)

    conditions = []
    if status is not None:
        conditions.append(Settlement.status == status)
    if provider_id is not None:
        conditions.append(Settlement.provider_id == provider_id)

    count_stmt = select(func.count()).select_from(Settlement)
    if conditions:
        count_stmt = count_stmt.where(*conditions)
    total = (await session.execute(count_stmt)).scalar_one()

    # 服务商名用 inner join：结算单的外键是 RESTRICT，
    # 没有服务商的结算单在库里不存在（真出现了也说明数据坏了）。
    stmt = select(
        Settlement.id,
        ServiceProvider.name,
        Settlement.period_start,
        Settlement.period_end,
        Settlement.total_amount,
        Settlement.commission_amount,
        Settlement.net_amount,
        Settlement.status,
        Settlement.confirmed_at,
    ).join(ServiceProvider, ServiceProvider.id == Settlement.provider_id)
    if conditions:
        stmt = stmt.where(*conditions)
    stmt = stmt.order_by(Settlement.id.desc()).offset((page - 1) * limit).limit(limit)

    rows = (await session.execute(stmt)).all()
    return [PlatformSettlementRow(*row) for row in rows], total


async def list_settlement_providers(
    session: AsyncSession,
) -> list[PlatformSettlementProviderOption]:
    """返回筛选栏用的服务商选项（有过结算单的服务商）。

    **为什么要单独查**：平台侧的服务商列表接口（/api/v1/platform/providers）
    只对平台管理员开放，而结算单列表财务也要用——财务调不了那个接口。
    所以列表接口自己带上筛选选项（与订单总览同一做法）。

    **选项不受状态筛选影响**：状态筛的是「哪几张单」，
    下拉里的服务商是「有哪些家」，两者不是一回事——只列**有过结算单**的
    服务商（没结算单的服务商筛出来一定是空的，列出来只是给筛选栏添噪音）。

    排序按 id（不按名称）：与别处的列表同一口径，也保证顺序稳定。
    """
    rows = (
        await session.execute(
            select(ServiceProvider.id, ServiceProvider.name)
            .join(Settlement, Settlement.provider_id == ServiceProvider.id)
            .distinct()
            .order_by(ServiceProvider.id)
        )
    ).all()
    return [
        PlatformSettlementProviderOption(id=provider_id, name=name)
        for provider_id, name in rows
    ]
