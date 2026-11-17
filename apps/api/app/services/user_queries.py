"""用户侧只读查询 service：品类树、服务项、时段余量、我的订单。

四条硬约束（每一条都有测试盯着）：

1. **身份只从 token 来**（R5）：所有订单相关的查询都带
   ``Order.user_id == 当前用户`` 这个谓词，接口层根本没有「查谁的订单」
   这种入参。「订单不存在」与「订单不属于你」共用同一个异常、同一句话
   （404 同构），调用方没法靠错误差异探测别人的订单存不存在、归谁。
2. **只读**：这个模块只 select，不 insert / update / delete。
   写操作一律走各自的 service（下单 / 派单 / 服务流转 / 结算）。
3. **分页有上限**：limit 收敛到 [1, MAX_PAGE_LIMIT]，offset 不为负。
   上限是服务端的**保证**（任何情况下都不会一页返回超过 100 条），
   不是对客户端的请求校验——传了超过 100 的值会被收敛，而不是报错。
4. **时段余量只有一个口径**：available = capacity - used，
   由 domain.slot_rule.available 算，这里不另写一套规则。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timezone import today as business_today
from app.domain.slot_rule import available as remaining_of
from app.models.catalog import ServiceCategory, ServiceItem
from app.models.enums import CatalogStatus, OrderStatus, PayStatus
from app.models.order import Order
from app.models.schedule_slot import ScheduleSlot
from app.services.errors import (
    CatalogNotFoundError,
    ItemNotFoundError,
    OrderNotFoundError,
)

__all__ = [
    "CategoryRow",
    "DEFAULT_PAGE_LIMIT",
    "MAX_PAGE_LIMIT",
    "OrderRow",
    "ServiceItemRow",
    "SlotRow",
    "get_service_item",
    "get_user_order",
    "list_categories",
    "list_category_items",
    "list_item_slots",
    "list_user_orders",
    "today",
]

# 订单列表的默认每页条数
DEFAULT_PAGE_LIMIT = 20

# 订单列表每页条数的上限。超过它会被收敛到这个值（不报错）。
MAX_PAGE_LIMIT = 100

# 与下单 / 服务流转一致的「订单不存在」文案模板。
# 「不存在」与「不属于你」共用这一句，调用方无法靠差异探测（R5）。
_ORDER_NOT_FOUND_DETAIL = "订单不存在：order_no={order_no}"

# 与下单 service 一致的「服务项不存在」文案
_ITEM_NOT_FOUND_DETAIL = "服务项不存在：item_id={item_id}"

# 与下单 service 一致的「品类不存在」文案
_CATEGORY_NOT_FOUND_DETAIL = "品类不存在：category_id={category_id}"


@dataclass
class CategoryRow:
    """品类节点（含子品类）。"""

    id: int
    name: str
    parent_id: int | None
    sort_order: int
    children: list["CategoryRow"] = field(default_factory=list)


@dataclass(frozen=True)
class ServiceItemRow:
    """服务项摘要。"""

    id: int
    category_id: int
    name: str
    base_price: Decimal
    duration_min: int


@dataclass(frozen=True)
class SlotRow:
    """时段余量。"""

    id: int
    item_id: int
    date: date
    start_time: time
    end_time: time
    capacity: int
    used: int
    available: int


@dataclass(frozen=True)
class OrderRow:
    """订单 + 关联的服务项与时段（列表与详情共用）。"""

    id: int
    order_no: str
    status: OrderStatus
    pay_status: PayStatus
    amount: Decimal
    item_id: int
    item_name: str
    slot_id: int
    slot_date: date
    slot_start_time: time
    slot_end_time: time
    address_id: int
    created_at: datetime
    # 完成时间：客户确认完成（或自动确认）时才写，没完成就是空。
    # 详情接口把它带给前端，列表接口不用（列表 schema 里没有这个字段）。
    completed_at: datetime | None


def today() -> date:
    """应用口径下的「今天」。

    按**业务时区**算（默认 Asia/Shanghai，见 ``app.core.timezone``）：
    面向国内用户，「今天」是国内的那个白天。

    之前这里算的是 UTC 日期——UTC 23:30（国内次日 07:30）下单时，
    UTC 日期还停在昨天，于是「今天」比用户以为的早一天，
    查当天时段、过滤订单都会差一天。
    """
    return business_today()


async def list_categories(session: AsyncSession) -> list[CategoryRow]:
    """返回品类树（一级品类，每个带自己的子树）。

    规则：

    - 只返回**启用**的品类；父品类停用时它的子树也一起不出现
      （停用意味着这一支整体下架，不是只藏起父节点）；
    - 子品类递归嵌套；
    - 排序按 sort_order 升序，同值按 id 升序（保证结果稳定）。
    """
    rows = (
        await session.execute(
            select(
                ServiceCategory.id,
                ServiceCategory.name,
                ServiceCategory.parent_id,
                ServiceCategory.sort_order,
            )
            .where(ServiceCategory.status == CatalogStatus.ACTIVE)
            .order_by(ServiceCategory.sort_order, ServiceCategory.id)
        )
    ).all()

    children_by_parent: dict[int | None, list[CategoryRow]] = {}
    for category_id, name, parent_id, sort_order in rows:
        node = CategoryRow(
            id=category_id,
            name=name,
            parent_id=parent_id,
            sort_order=sort_order,
        )
        children_by_parent.setdefault(parent_id, []).append(node)

    def attach(node: CategoryRow, seen: set[int]) -> None:
        """把 node 的子树挂上去。seen 防住脏数据造成的环。"""
        for child in children_by_parent.get(node.id, []):
            if child.id in seen:
                continue
            seen.add(child.id)
            node.children.append(child)
            attach(child, seen)

    roots = children_by_parent.get(None, [])
    for root in roots:
        attach(root, {root.id})
    return roots


async def list_category_items(
    session: AsyncSession, *, category_id: int
) -> list[ServiceItemRow]:
    """返回某个品类下的服务项（只含直接归属该品类的、且启用的）。

    子品类下的服务项**不在**这里返回：前端拿到品类树后，
    自己按 category_id 再逐个查子品类的服务项。

    品类不存在或已停用 -> CatalogNotFoundError（404）。
    「不存在」与「已停用」共用一句话，不泄露品类状态。
    """
    row = (
        await session.execute(
            select(ServiceCategory.id, ServiceCategory.status).where(
                ServiceCategory.id == category_id
            )
        )
    ).one_or_none()
    if row is None or row.status != CatalogStatus.ACTIVE:
        raise CatalogNotFoundError(
            _CATEGORY_NOT_FOUND_DETAIL.format(category_id=category_id)
        )

    rows = (
        await session.execute(
            select(
                ServiceItem.id,
                ServiceItem.category_id,
                ServiceItem.name,
                ServiceItem.base_price,
                ServiceItem.duration_min,
            )
            .where(
                ServiceItem.category_id == category_id,
                ServiceItem.status == CatalogStatus.ACTIVE,
            )
            .order_by(ServiceItem.id)
        )
    ).all()
    return [
        ServiceItemRow(
            id=item_id,
            category_id=item_category_id,
            name=name,
            base_price=base_price,
            duration_min=duration_min,
        )
        for item_id, item_category_id, name, base_price, duration_min in rows
    ]


async def get_service_item(
    session: AsyncSession, *, item_id: int
) -> ServiceItemRow:
    """返回单个服务项的详情。

    服务项不存在或已停用 -> ItemNotFoundError（404）。
    「不存在」与「已停用」共用一句话，不泄露服务项状态——
    和列表接口的口径一致：目录里看不到的服务项，单独查也查不到。
    """
    row = (
        await session.execute(
            select(
                ServiceItem.id,
                ServiceItem.category_id,
                ServiceItem.name,
                ServiceItem.base_price,
                ServiceItem.duration_min,
            ).where(
                ServiceItem.id == item_id,
                ServiceItem.status == CatalogStatus.ACTIVE,
            )
        )
    ).one_or_none()
    if row is None:
        raise ItemNotFoundError(_ITEM_NOT_FOUND_DETAIL.format(item_id=item_id))
    return ServiceItemRow(*row)


async def list_item_slots(
    session: AsyncSession, *, item_id: int, on_date: date
) -> list[SlotRow]:
    """返回某个服务项在某天的可预约时段。

    只返回**还能约**的时段：

    - 日期 >= 今天（过去的时段不返回）；
    - available = capacity - used > 0（已约满的不返回）。

    service_item 不存在或已停用 -> ItemNotFoundError（404）。
    """
    row = (
        await session.execute(
            select(ServiceItem.id, ServiceItem.status).where(ServiceItem.id == item_id)
        )
    ).one_or_none()
    if row is None or row.status != CatalogStatus.ACTIVE:
        raise ItemNotFoundError(_ITEM_NOT_FOUND_DETAIL.format(item_id=item_id))

    if on_date < today():
        # 过去的日期一律没有可约时段（不是错误，是空列表）
        return []

    rows = (
        await session.execute(
            select(
                ScheduleSlot.id,
                ScheduleSlot.item_id,
                ScheduleSlot.date,
                ScheduleSlot.start_time,
                ScheduleSlot.end_time,
                ScheduleSlot.capacity,
                ScheduleSlot.used,
            )
            .where(
                ScheduleSlot.item_id == item_id,
                ScheduleSlot.date == on_date,
            )
            .order_by(ScheduleSlot.start_time)
        )
    ).all()

    result: list[SlotRow] = []
    for slot_id, slot_item_id, slot_date, start_time, end_time, capacity, used in rows:
        left = remaining_of(capacity, used)
        if left <= 0:
            # 已约满：前端不需要看到它（点进去也是 409）
            continue
        result.append(
            SlotRow(
                id=slot_id,
                item_id=slot_item_id,
                date=slot_date,
                start_time=start_time,
                end_time=end_time,
                capacity=capacity,
                used=used,
                available=left,
            )
        )
    return result


async def list_user_orders(
    session: AsyncSession, *, user_id: int, limit: int, offset: int
) -> tuple[list[OrderRow], int]:
    """返回当前用户的订单列表（按创建时间倒序）与订单总数。

    排序：created_at 倒序，同一时间用 id 倒序兜底。
    加 id 是因为 created_at 精度有限（同一批插入的订单时间可能完全相同），
    没有第二排序键时分页会在两页之间重复或漏掉同一行。

    过滤条件里带着 ``user_id``：这是 R5 的落点——列表只可能返回自己的订单。
    """
    effective_limit = min(max(limit, 1), MAX_PAGE_LIMIT)
    effective_offset = max(offset, 0)

    total = (
        await session.execute(
            select(func.count())
            .select_from(Order)
            .where(Order.user_id == user_id)
        )
    ).scalar_one()

    rows = (
        await session.execute(
            _order_select()
            .where(Order.user_id == user_id)
            .order_by(Order.created_at.desc(), Order.id.desc())
            .limit(effective_limit)
            .offset(effective_offset)
        )
    ).all()
    return [OrderRow(*row) for row in rows], total


async def get_user_order(
    session: AsyncSession, *, user_id: int, order_no: str
) -> OrderRow:
    """返回当前用户的一笔订单详情。

    查不到（不存在 / 不属于当前用户）-> OrderNotFoundError（404）。
    两种情况的响应完全一样，调用方无法区分（R5）。
    """
    row = (
        await session.execute(
            _order_select().where(
                Order.order_no == order_no,
                Order.user_id == user_id,
            )
        )
    ).first()
    if row is None:
        raise OrderNotFoundError(
            _ORDER_NOT_FOUND_DETAIL.format(order_no=order_no)
        )
    return OrderRow(*row)


def _order_select():
    """订单 + 服务项名称 + 时段信息的查询。

    内连接：slot_id / item_id 都是外键且删除时 RESTRICT，
    订单引用的行必然存在，内连接不会丢行。
    """
    return select(
        Order.id,
        Order.order_no,
        Order.status,
        Order.pay_status,
        Order.amount,
        Order.item_id,
        ServiceItem.name,
        Order.slot_id,
        ScheduleSlot.date,
        ScheduleSlot.start_time,
        ScheduleSlot.end_time,
        Order.address_id,
        Order.created_at,
        Order.completed_at,
    ).join(
        ServiceItem, ServiceItem.id == Order.item_id
    ).join(
        ScheduleSlot, ScheduleSlot.id == Order.slot_id
    )
