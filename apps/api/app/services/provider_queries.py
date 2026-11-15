"""服务商侧只读查询 service：待派单订单列表、本商师傅列表。

三条硬约束（每一条都有测试盯着）：

1. **归属只从 token 来**（R1/R5）：``provider_id`` 是函数参数，
   但调用方（api 层）拿到的是 ``CurrentUser.provider_id``——
   接口层根本没有「查哪个服务商的订单」这种入参。
2. **只读**：这个模块只 select，不 insert / update / delete。
   写操作一律走各自的 service（派单见 app.services.dispatch）。
3. **分页有上限**：limit 收敛到 [1, MAX_PAGE_LIMIT]，offset 不为负，
   与用户侧订单列表（app.services.user_queries）同一套口径。

**「本商待派单」到底包含哪些订单**（最容易搞错的一处，单独说明）：

派单 service（app.services.dispatch）允许派单的条件是：

    status == PENDING_DISPATCH 且
    (provider_id IS NULL  或  (provider_id == 本商 且 master_id IS NULL))

这后半截谓词**直接引用** ``app.services.dispatch.dispatchable_scope``——
本模块不再自己抄一份，两边共用同一个事实来源。

待派单池由两部分组成：

- **公共池**（``provider_id IS NULL``）：客户付完款、还没人接的单。
  归属还没定，任何服务商都能派——所以它对每个服务商都可见。
  （下单时 provider_id 写死为空，见 app.services.place_order。）
- **本商专属**（``provider_id == 本商 且 master_id IS NULL``）：
  师傅拒单后退回本商的单。归属已经是本商的，且当前没有承接人，可以重新派。

别家的单（``provider_id == 别家``）一律不出现。

本模块的可见范围与派单 service 的可派范围**是同一个谓词**
（``dispatchable_scope``）：列表里不出现派不了的单（否则前端点「派单」
只会拿到一个报错），列表里出现的单都真的能派。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog import ServiceItem
from app.models.enums import MasterStatus, OrderStatus, PayStatus
from app.models.order import Order
from app.models.provider import Master
from app.models.schedule_slot import ScheduleSlot
from app.services.dispatch import dispatchable_scope

__all__ = [
    "ProviderMasterRow",
    "ProviderOrderRow",
    "list_provider_masters",
    "list_provider_orders",
]

# 分页口径与用户侧订单列表一致（见 app.services.user_queries）
DEFAULT_PAGE_LIMIT = 20
MAX_PAGE_LIMIT = 100


@dataclass(frozen=True)
class ProviderOrderRow:
    """待派单列表里的一笔订单（+ 服务项名称与预约时段）。"""

    id: int
    order_no: str
    status: OrderStatus
    pay_status: PayStatus
    amount: Decimal
    item_id: int
    item_name: str
    slot_date: date
    slot_start_time: time
    created_at: datetime


@dataclass(frozen=True)
class ProviderMasterRow:
    """本商师傅的一项。"""

    id: int
    real_name: str
    rating: Decimal | None
    status: MasterStatus


def provider_scope_filter(status: OrderStatus, provider_id: int):
    """构造「本商可见、且处于指定状态」的订单谓词。

    状态条件与归属条件**必须拼在同一个谓词里**：分两次 where 的话，
    少写一个就是「状态过滤没生效」——列表里会混进别的状态的订单，
    而总数也跟着算错。

    待派单（PENDING_DISPATCH）与其它状态的口径不一样，理由见模块头：

    - 待派单：公共池（还没归属） + 本商专属（拒单退回的）；
    - 其它状态：只看 ``provider_id == 本商``。
      这一支不能带上「未归属」的订单——比如还没付款（PENDING_PAY）的单
      provider_id 是空的，让每个服务商都看见等于把全平台的单摊开给所有人。
    """
    if status == OrderStatus.PENDING_DISPATCH:
        # 可派范围直接引用派单 service 的谓词（单一事实来源），
        # 不在这里重写一份：两份写法迟早漂移，漂了就是「列表里有、派不了」。
        owned = dispatchable_scope(provider_id)
    else:
        owned = Order.provider_id == provider_id
    return and_(Order.status == status, owned)


async def list_provider_orders(
    session: AsyncSession,
    *,
    provider_id: int,
    status: OrderStatus,
    limit: int = DEFAULT_PAGE_LIMIT,
    offset: int = 0,
) -> tuple[list[ProviderOrderRow], int]:
    """返回本商可见的、处于指定状态的订单（按创建时间倒序）与总数。

    排序：created_at 倒序，同一时间用 id 倒序兜底
    （created_at 精度有限，同一批插入的订单时间可能完全相同，
    没有第二排序键时分页会在两页之间重复或漏掉同一行）。

    可见范围见模块头与 ``provider_scope_filter``。
    """
    effective_limit = min(max(limit, 1), MAX_PAGE_LIMIT)
    effective_offset = max(offset, 0)
    scope = provider_scope_filter(status, provider_id)

    total = (
        await session.execute(select(func.count()).select_from(Order).where(scope))
    ).scalar_one()

    rows = (
        await session.execute(
            select(
                Order.id,
                Order.order_no,
                Order.status,
                Order.pay_status,
                Order.amount,
                Order.item_id,
                ServiceItem.name,
                ScheduleSlot.date,
                ScheduleSlot.start_time,
                Order.created_at,
            )
            .join(ServiceItem, ServiceItem.id == Order.item_id)
            .join(ScheduleSlot, ScheduleSlot.id == Order.slot_id)
            .where(scope)
            .order_by(Order.created_at.desc(), Order.id.desc())
            .limit(effective_limit)
            .offset(effective_offset)
        )
    ).all()

    return [ProviderOrderRow(*row) for row in rows], total


async def list_provider_masters(
    session: AsyncSession, *, provider_id: int
) -> list[ProviderMasterRow]:
    """返回本商的师傅列表（按 id 升序）。

    过滤条件里带着 ``provider_id``：别的服务商的师傅一律不出现。

    所有状态的师傅都返回（含停用 / 休假），``status`` 字段交给前端显示，
    由派单的人决定派给谁——服务端只负责「不越界」，不替人做经营判断。
    """
    rows = (
        await session.execute(
            select(
                Master.id,
                Master.real_name,
                Master.rating,
                Master.status,
            )
            .where(Master.provider_id == provider_id)
            .order_by(Master.id)
        )
    ).all()
    return [ProviderMasterRow(*row) for row in rows]
