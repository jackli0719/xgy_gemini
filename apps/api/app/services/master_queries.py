"""师傅端只读查询 service：我的订单列表、订单详情、我的资料。

五条硬约束（每一条都有测试盯着）：

1. **身份只从 token 来**（R1/R5）：师傅身份由 ``current_user.user_id``
   查 master 表得到，**不从入参取**。三个函数的签名里都没有 master_id /
   user_id 参数——不是「约定别传」，是「传不进来」。
   师傅的归属权威来源是 master 表，不是 ``user.provider_id``：
   一个登录用户最多对应一个师傅身份（uq_master_user_id 唯一约束保证）。
2. **只读**：这个模块只 select，不 insert / update / delete。
   写操作一律走各自的 service（接单 / 拒单见 app.services.master_action，
   开工 / 完工见 app.services.service_flow）。
3. **归属写进 SQL 谓词**：订单查询永远带 ``Order.master_id == 我的 master_id``，
   「订单不存在」与「订单不是我的」共用同一个异常、同一句话（404 同构），
   调用方没法靠错误差异探测别人的订单存不存在、归谁。
   列表里也带上门地址（师傅在路上就得看地址）——地址属于**这笔订单**，
   而订单已经被这条谓词过滤过，所以不会外泄别人的地址。
4. **分页有上限**：limit 收敛到 [1, MAX_PAGE_LIMIT]，offset 不为负，
   与用户侧订单列表（app.services.user_queries）同一套口径。
5. **查询不按师傅状态过滤**：停用 / 休假的师傅照样能查自己的单。
   能不能干活由**写操作**自己挡（接单 / 开工 / 完工 -> 409，
   见 app.services.master_action 与 app.services.service_flow）：
   读权限与干活权限是两回事，把它们混成一条会让被停用的师傅连单都看不到，
   他手上的单就没人能退回去了（拒单是允许的）。

**列表为什么只有三种状态**：师傅的工作队列只有三组——待接单（PENDING_ACCEPT）、
已接单待开工（ACCEPTED）、服务中（IN_SERVICE）。
这个集合是业务规则，落在 ``app.models.enums.MasterOrderStatus``（**事实来源**）：
接口层用窄枚举把别的状态变成 422，service 用同一份定义做**运行时校验**
（``_resolve_master_order_status``），把不合法的状态挡在碰库之前——
两道防线共用一份定义，不会各写各的。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser
from app.models.address import Address
from app.models.catalog import ServiceItem
from app.models.enums import MasterOrderStatus, MasterStatus, OrderStatus
from app.models.order import Order
from app.models.provider import Master, ServiceProvider
from app.models.schedule_slot import ScheduleSlot
from app.services.errors import (
    MasterOrderStatusNotAllowedError,
    MasterQueryForbiddenError,
    OrderNotFoundError,
)

__all__ = [
    "DEFAULT_PAGE_LIMIT",
    "MAX_PAGE_LIMIT",
    "MasterIdentity",
    "MasterOrderDetailRow",
    "MasterOrderRow",
    "MasterProfileRow",
    "get_master_order",
    "get_master_profile",
    "list_master_orders",
    "resolve_master",
]

# 分页口径与用户侧订单列表一致（见 app.services.user_queries）
DEFAULT_PAGE_LIMIT = 20
MAX_PAGE_LIMIT = 100

# 与下单 / 接单 / 服务流转一致的「订单不存在」文案模板。
# 「不存在」与「不是我的」共用这一句，调用方无法靠差异探测（R5）。
_ORDER_NOT_FOUND_DETAIL = "订单不存在：order_no={order_no}"

# 「这个账号没有师傅身份」的文案。与接单 / 服务流转那边写的是同一句，
# 免得同一个问题在两个接口里长得不一样。
_NO_MASTER_IDENTITY_DETAIL = "当前账号没有师傅身份"

# 师傅端可查的订单状态集合（事实来源：app.models.enums.MasterOrderStatus）。
#
# 为什么 service 里还要有一份：接口层的窄枚举只在「走 HTTP」时有效，
# service 也会被直接调用（测试、将来的别的入口），那时类型提示挡不住
# 运行时传错值——``OrderStatus.COMPLETED`` 照样能传进来。
# 少了这道校验，一次本该被拒的查询会变成「返回一批比工作队列宽得多的单」。
# 与 app.services.master_management 的 _SETTABLE_STATUS_VALUES 同一套写法。
_MASTER_ORDER_STATUS_VALUES = frozenset(s.value for s in MasterOrderStatus)


@dataclass(frozen=True)
class MasterIdentity:
    """当前登录账号对应的师傅身份（从 master 表查出来的）。"""

    id: int
    provider_id: int
    real_name: str
    rating: Decimal | None
    status: MasterStatus


@dataclass(frozen=True)
class MasterOrderRow:
    """师傅端订单列表里的一笔订单（+ 服务项名称、预约时段与上门地址）。

    字段顺序 **必须** 与 ``_order_select()`` 的列顺序严格一致——
    service 用位置参数构造（``MasterOrderRow(*row)``），
    对不上就会把「服务项名称」当成「预约日期」塞进去。
    """

    id: int
    order_no: str
    status: OrderStatus
    amount: Decimal
    item_id: int
    item_name: str
    slot_id: int
    slot_date: date
    slot_start_time: time
    slot_end_time: time
    created_at: datetime
    # 完成时间：客户确认完成（或自动确认）时才写，没完成就是空。
    # 详情响应把它带给师傅；列表响应不用（列表 schema 里没有这个字段）。
    completed_at: datetime | None
    # 上门地址：列表也要给（师傅在路上就得看地址）。
    # 地址属于**这笔订单**，而订单已经按归属谓词过滤过
    # （``Order.master_id == 我的 master_id``），所以不会外泄别人的地址。
    address_region: str
    address_detail: str


@dataclass(frozen=True)
class MasterOrderDetailRow(MasterOrderRow):
    """订单详情：多了客户联系方式。

    联系方式**只对承接这笔订单的师傅可见**——他得知道找谁。
    可见范围由 ``Order.master_id == 我的 master_id`` 这条谓词保证。

    地址在基类里（列表也带），这里只补联系方式；
    字段顺序同样是「基类在前、子类在后」，与 ``_detail_select()`` 的列顺序对齐。
    """

    customer_contact: str
    customer_phone: str


@dataclass(frozen=True)
class MasterProfileRow:
    """师傅自己的资料（姓名 / 评分 / 状态 / 所属服务商）。"""

    real_name: str
    rating: Decimal | None
    status: MasterStatus
    provider_name: str


async def resolve_master(
    session: AsyncSession, current_user: CurrentUser
) -> MasterIdentity:
    """按 token 里的 user_id 查出当前账号的师傅身份。

    查不到（这个账号在 master 表里没有师傅身份）-> MasterQueryForbiddenError（403）。

    token 里带了 provider_id（服务商账号同时也是师傅）时，
    它必须与 master.provider_id 一致，否则这个账号的身份是错乱的，
    不能让它看订单——与接单 / 服务流转那边的口径一致。
    """
    row = (
        await session.execute(
            select(
                Master.id,
                Master.provider_id,
                Master.real_name,
                Master.rating,
                Master.status,
            ).where(Master.user_id == current_user.user_id)
        )
    ).one_or_none()
    if row is None:
        raise MasterQueryForbiddenError(_NO_MASTER_IDENTITY_DETAIL)
    if current_user.provider_id is not None and current_user.provider_id != row.provider_id:
        raise MasterQueryForbiddenError("当前账号的师傅身份与服务商归属不一致")
    return MasterIdentity(
        id=row.id,
        provider_id=row.provider_id,
        real_name=row.real_name,
        rating=row.rating,
        status=row.status,
    )


async def list_master_orders(
    session: AsyncSession,
    *,
    master_id: int,
    status: MasterOrderStatus | OrderStatus | str,
    limit: int = DEFAULT_PAGE_LIMIT,
    offset: int = 0,
) -> tuple[list[MasterOrderRow], int]:
    """返回派给我、且处于指定状态的订单（按创建时间倒序）与总数。

    ``status`` 只允许 MasterOrderStatus 里的三种（业务规则）。
    接口层用窄枚举把别的状态挡成 422，这里**再挡一次**（运行时校验，
    见 ``_resolve_master_order_status``）：有人绕过接口层直接调 service 时，
    别的状态不该被当成一次合法查询。

    归属谓词 ``Order.master_id == master_id`` 是这个接口的**唯一**闸门：
    别人的单既不在列表里，详情里也查不到（404 同构）。
    """
    # 状态校验放在碰库之前：不合法的状态连数据都不该看一眼
    resolved_status = _resolve_master_order_status(status)

    effective_limit = min(max(limit, 1), MAX_PAGE_LIMIT)
    effective_offset = max(offset, 0)
    scope = and_(
        Order.master_id == master_id,
        Order.status == OrderStatus(resolved_status.value),
    )

    total = (
        await session.execute(select(func.count()).select_from(Order).where(scope))
    ).scalar_one()

    rows = (
        await session.execute(
            _order_select()
            .where(scope)
            .order_by(Order.created_at.desc(), Order.id.desc())
            .limit(effective_limit)
            .offset(effective_offset)
        )
    ).all()
    return [MasterOrderRow(*row) for row in rows], total


async def get_master_order(
    session: AsyncSession, *, master_id: int, order_no: str
) -> MasterOrderDetailRow:
    """返回派给我的一笔订单详情。

    查不到（不存在 / 不是派给我的）-> OrderNotFoundError（404）。
    两种情况的响应完全一样，调用方无法区分（R5）。

    详情**不按订单状态过滤**：已接单、服务中、待确认、已完成的单都查得到——
    师傅要回看自己做过什么。能不能推进（开工 / 完工）由写操作自己挡。
    """
    row = (
        await session.execute(
            _detail_select().where(
                Order.order_no == order_no,
                Order.master_id == master_id,
            )
        )
    ).first()
    if row is None:
        raise OrderNotFoundError(_ORDER_NOT_FOUND_DETAIL.format(order_no=order_no))
    return MasterOrderDetailRow(*row)


async def get_master_profile(
    session: AsyncSession, *, master_id: int
) -> MasterProfileRow:
    """返回师傅自己的资料（姓名 / 评分 / 状态 / 所属服务商名称）。

    查不到 -> MasterQueryForbiddenError（403）：这个 master_id 对应的师傅
    已经不在了（正常情况下不会发生——调用方拿到的 id 来自 resolve_master）。
    """
    row = (
        await session.execute(
            select(
                Master.real_name,
                Master.rating,
                Master.status,
                ServiceProvider.name,
            )
            .join(ServiceProvider, ServiceProvider.id == Master.provider_id)
            .where(Master.id == master_id)
        )
    ).one_or_none()
    if row is None:
        raise MasterQueryForbiddenError(_NO_MASTER_IDENTITY_DETAIL)
    return MasterProfileRow(*row)


def _resolve_master_order_status(
    status: MasterOrderStatus | OrderStatus | str,
) -> MasterOrderStatus:
    """把传入的状态收敛成「师傅端可查」的 ``MasterOrderStatus``。

    **为什么要在这里再挡一次**：接口层用窄枚举（``MasterOrderStatus``）
    把别的状态变成 422，但那条防线只在「走接口」时有效。service 也会被
    直接调用（测试、将来的别的入口），那时类型提示挡不住运行时传错值——
    ``OrderStatus.COMPLETED`` 照样能传进来。

    所以这里按同一份事实来源（``app.models.enums.MasterOrderStatus``）
    显式校验一遍：不在可查集合里就抛业务异常，而不是照单全收——
    一次本该被拒的查询，会变成「返回一批比工作队列宽得多的单」
    （师傅会看到自己已完成的单）。

    非法状态映射成 400（``MasterOrderStatusNotAllowedError``）：
    客户端改了请求内容才可能解决，不是 404、也不是 500。
    """
    value = status.value if isinstance(status, Enum) else str(status)
    if value not in _MASTER_ORDER_STATUS_VALUES:
        raise MasterOrderStatusNotAllowedError(
            "师傅端只支持这三种状态：{}，收到：{}".format(
                " / ".join(sorted(_MASTER_ORDER_STATUS_VALUES)),
                value,
            )
        )
    return MasterOrderStatus(value)


def _order_select():
    """订单 + 服务项名称 + 时段信息 + 上门地址的查询（列表用）。

    内连接：slot_id / item_id / address_id 都是外键且删除时 RESTRICT，
    订单引用的行必然存在，内连接不会丢行。

    **列顺序与 ``MasterOrderRow`` 的字段顺序一一对应**——service 用位置参数
    构造（``MasterOrderRow(*row)``），对不上就会串列。
    """
    return select(
        Order.id,
        Order.order_no,
        Order.status,
        Order.amount,
        Order.item_id,
        ServiceItem.name,
        Order.slot_id,
        ScheduleSlot.date,
        ScheduleSlot.start_time,
        ScheduleSlot.end_time,
        Order.created_at,
        Order.completed_at,
        Address.region,
        Address.detail,
    ).join(
        ServiceItem, ServiceItem.id == Order.item_id
    ).join(
        ScheduleSlot, ScheduleSlot.id == Order.slot_id
    ).join(
        Address, Address.id == Order.address_id
    )


def _detail_select():
    """订单详情查询：比列表多出客户联系方式。

    地址的 join 已经在 ``_order_select()`` 里了，这里只补两列
    （contact / phone）——地址表的 join 再写一遍会变成「同一张表连两次」。

    地址也在谓词里（``Order.master_id == 我的 master_id``）：
    不是我的单，地址一个字节都不往外发。
    """
    return _order_select().add_columns(
        Address.contact,
        Address.phone,
    )
