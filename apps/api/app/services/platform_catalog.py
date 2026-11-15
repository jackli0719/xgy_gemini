"""平台侧目录管理 service（PLAT-02）：品类树 + 服务项 + 改价。

平台侧管的是**全平台**的目录：建品类、建物类下的服务项、改名改价、
上下架。与用户侧目录查询的根本区别是——用户侧只看得到**启用**的，
平台侧看全部（不然没法把停用的东西重新启用）。

与 PLAT-01 的服务商管理是同一条思路：
**「管哪一个」是请求的一部分**（路径里的 id），
**「我是谁」永远只从 token 来**（CurrentUser）。

五条硬约束（每一条都有测试盯着）：

1. **operator 只从 CurrentUser 取**：函数签名里没有 operator 参数，
   审计日志里的操作人由服务端从 token 里的 role / user_id 填。
2. **改状态用条件 UPDATE，禁止读-改-写**：
   ``WHERE id = ? AND status = 期望旧状态``。判定交给数据库的行锁裁决——
   两个人同时改同一个品类，只有一个人能成功，另一个拿到 409。
   读旧状态（审计要用）因此**不是**判定依据。
3. **版本号（乐观锁）**：条件 UPDATE 的谓词里还有一条
   ``date_trunc('milliseconds', updated_at) = 期望版本号``。
   状态没变但价格被别人改了，只判状态是发现不了的——两个人都看到
   ``ACTIVE``，第二个人的改价会把第一个人的改价无声地盖掉。
   版本号管的是「这一行有没有被别人动过」，与改哪个字段无关，
   品类与服务项用的是同一套。
4. **变更必须留痕**：同事务内写 audit_log
   （target_type='service_category' / 'service_item'、field_name=字段名、
   old / new 值、操作人）。**价格变更（base_price）尤其要留痕**——
   R3 追的就是「谁改的价、改成多少」。
   **new 值取自 ``UPDATE ... RETURNING``**：落库的值才是真相
   （请求说 150.5，库里存的是 150.50，审计要写 150.50）。
5. **目录对象不存在 -> 404**；**并发冲突 -> 409**。
6. **角色不对 -> 403**：正常由依赖层（``require_platform_staff``）挡住，
   service 这边再挡一道是兜底。

**「期望旧状态」从哪来**：客户端可以带 ``expected_status``
（它以为的旧状态）；不传就用服务端刚读到的旧状态。
两种情况下条件 UPDATE 的谓词都是「这一行现在的状态必须还是我看到的那个」，
所以「读完之后、写之前被别人改了」也会被判成冲突（409）。

**为什么版本号用 updated_at 而不是专门加一列**：
updated_at 本来就在（TimestampMixin），每次写都刷新，不用迁移、不用
改表结构；专门的 version 列要多一个迁移 + 模型改动，收益只是省掉
一次毫秒截断。版本号取毫秒精度是因为前端经过 JS 的 Date 会丢微秒——
精度定得比前端能表达的还细，就会出现「明明没冲突却报 409」。

（临时校验用：本次改动只加注释，不碰任何逻辑。）
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser
from app.models.audit_log import AuditLog
from app.models.catalog import ServiceCategory, ServiceItem
from app.models.enums import CatalogStatus, OperatorType, UserRole
from app.services.errors import (
    PlatformCatalogConflictError,
    PlatformCatalogForbiddenError,
    PlatformCatalogNotFoundError,
)
from app.services.platform_scope import operator_type_for_platform_role

__all__ = [
    "PlatformCategory",
    "PlatformServiceItem",
    "create_category",
    "create_service_item",
    "list_catalog",
    "update_category",
    "update_service_item",
]

# 审计日志里的对象类型（审计表用 target_type + target_id 做软关联）
CATEGORY_AUDIT_TARGET_TYPE = "service_category"
ITEM_AUDIT_TARGET_TYPE = "service_item"

# 审计日志里记录的原因
CATEGORY_AUDIT_REASON = "平台调整品类"
ITEM_AUDIT_REASON = "平台调整服务项"
CATEGORY_CREATE_REASON = "平台创建品类"
ITEM_CREATE_REASON = "平台创建服务项"

# 「品类不存在」与「服务项不存在」
CATEGORY_NOT_FOUND_DETAIL = "品类不存在：category_id={category_id}"
ITEM_NOT_FOUND_DETAIL = "服务项不存在：item_id={item_id}"
PARENT_NOT_FOUND_DETAIL = "父品类不存在：parent_id={parent_id}"

# 「这一行已经被别人改过了」
CONFLICT_DETAIL = "{target}已被他人修改，请刷新后重试"

# 版本号的精度（毫秒）：比这更细的精度前端表达不出来
# （JS 的 Date 只有毫秒），定得更细就会出现「假冲突」。
VERSION_PRECISION = "milliseconds"

# 平台侧角色（与 app.core.auth.PLATFORM_STAFF_ROLES 一致）
PLATFORM_STAFF_ROLES = frozenset({UserRole.PLATFORM_ADMIN, UserRole.PLATFORM_OPS})


@dataclass(frozen=True)
class PlatformServiceItem:
    """一条服务项的快照。"""

    id: int
    category_id: int
    name: str
    base_price: Decimal
    duration_min: int
    status: CatalogStatus
    created_at: datetime
    updated_at: datetime


@dataclass
class PlatformCategory:
    """品类树上的一个节点（含子树与本品类下的服务项）。"""

    id: int
    name: str
    parent_id: int | None
    sort_order: int
    status: CatalogStatus
    updated_at: datetime
    items: list[PlatformServiceItem] = field(default_factory=list)
    children: list["PlatformCategory"] = field(default_factory=list)


# =====================================================================
# 查询
# =====================================================================


async def list_catalog(session: AsyncSession) -> list[PlatformCategory]:
    """返回品类树（每个节点带上自己直接归属的服务项）。

    **所有状态都返回**（含已停用）：平台侧要能看见停用的东西，
    否则没法把它们重新启用（与用户侧只给 ACTIVE 的口径不同）。

    排序：sort_order 升序，同值按 id 升序（保证结果稳定）。
    """
    category_rows = (
        await session.execute(
            select(
                ServiceCategory.id,
                ServiceCategory.name,
                ServiceCategory.parent_id,
                ServiceCategory.sort_order,
                ServiceCategory.status,
                ServiceCategory.updated_at,
            ).order_by(ServiceCategory.sort_order, ServiceCategory.id)
        )
    ).all()

    item_rows = (
        await session.execute(
            select(
                ServiceItem.id,
                ServiceItem.category_id,
                ServiceItem.name,
                ServiceItem.base_price,
                ServiceItem.duration_min,
                ServiceItem.status,
                ServiceItem.created_at,
                ServiceItem.updated_at,
            ).order_by(ServiceItem.id)
        )
    ).all()

    items_by_category: dict[int, list[PlatformServiceItem]] = {}
    for (
        item_id,
        category_id,
        name,
        base_price,
        duration_min,
        status,
        created_at,
        updated_at,
    ) in item_rows:
        items_by_category.setdefault(category_id, []).append(
            PlatformServiceItem(
                id=item_id,
                category_id=category_id,
                name=name,
                base_price=base_price,
                duration_min=duration_min,
                status=status,
                created_at=created_at,
                updated_at=updated_at,
            )
        )

    nodes: dict[int, PlatformCategory] = {}
    children_by_parent: dict[int | None, list[PlatformCategory]] = {}
    for category_id, name, parent_id, sort_order, status, updated_at in category_rows:
        node = PlatformCategory(
            id=category_id,
            name=name,
            parent_id=parent_id,
            sort_order=sort_order,
            status=status,
            updated_at=updated_at,
            items=items_by_category.get(category_id, []),
        )
        nodes[category_id] = node
        children_by_parent.setdefault(parent_id, []).append(node)

    def attach(node: PlatformCategory, seen: set[int]) -> None:
        """把子树挂上去。seen 防住脏数据造成的环。"""
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


# =====================================================================
# 品类
# =====================================================================


async def create_category(
    session: AsyncSession,
    *,
    name: str,
    parent_id: int | None = None,
    sort_order: int = 0,
    current_user: CurrentUser,
) -> PlatformCategory:
    """新建一个品类（初始状态：启用）。

    状态**不由请求体决定**：新建一律启用，要停用再调改接口。

    父品类不存在 -> 404（不能建在一个不存在的品类底下）。
    """
    operator_type = _require_platform_staff(current_user)

    async with session.begin():
        if parent_id is not None:
            parent_exists = (
                await session.execute(
                    select(ServiceCategory.id).where(ServiceCategory.id == parent_id)
                )
            ).scalar_one_or_none()
            if parent_exists is None:
                raise PlatformCatalogNotFoundError(
                    PARENT_NOT_FOUND_DETAIL.format(parent_id=parent_id)
                )

        category = ServiceCategory(
            name=name,
            parent_id=parent_id,
            sort_order=sort_order,
            status=CatalogStatus.ACTIVE,
        )
        session.add(category)
        await session.flush()

        session.add(
            AuditLog(
                operator_type=operator_type,
                operator_id=current_user.user_id,
                target_type=CATEGORY_AUDIT_TARGET_TYPE,
                target_id=category.id,
                # 平台侧操作不涉及具体服务商：留空（按服务商检索时不该命中）
                provider_id=None,
                field_name="created",
                old_value=None,
                new_value=name,
                reason=CATEGORY_CREATE_REASON,
            )
        )
        await session.flush()

        created = PlatformCategory(
            id=category.id,
            name=category.name,
            parent_id=category.parent_id,
            sort_order=category.sort_order,
            status=category.status,
            updated_at=category.updated_at,
            items=[],
        )

    return created


async def update_category(
    session: AsyncSession,
    *,
    category_id: int,
    name: str | None = None,
    sort_order: int | None = None,
    status: CatalogStatus | None = None,
    expected_status: CatalogStatus | None = None,
    expected_updated_at: datetime | None = None,
    current_user: CurrentUser,
) -> PlatformCategory:
    """改品类（名称 / 排序 / 状态），返回改完之后的快照。

    **条件 UPDATE**（不是读-改-写）::

        UPDATE service_category SET ...
        WHERE id = :id
          AND status = :期望旧状态
          AND date_trunc('milliseconds', updated_at) = :期望版本号

    一行都没改到 -> 409：这一行已经被别人改过了。
    品类不存在 -> 404。

    每一个**真正变了**的字段都写一条 audit_log（old / new 值都有）。
    new 值取自 ``UPDATE ... RETURNING``——落库的值才是真相。
    """
    operator_type = _require_platform_staff(current_user)

    async with session.begin():
        # 1) 旧值：审计要用，判定不靠它。
        old = (
            await session.execute(
                select(
                    ServiceCategory.id,
                    ServiceCategory.name,
                    ServiceCategory.parent_id,
                    ServiceCategory.sort_order,
                    ServiceCategory.status,
                    ServiceCategory.updated_at,
                ).where(ServiceCategory.id == category_id)
            )
        ).one_or_none()
        if old is None:
            raise PlatformCatalogNotFoundError(
                CATEGORY_NOT_FOUND_DETAIL.format(category_id=category_id)
            )
        (
            old_id,
            old_name,
            old_parent_id,
            old_sort_order,
            old_status,
            old_updated_at,
        ) = old

        # 2) 期望旧状态与期望版本号：客户端说它以为的，不说就用刚读到的。
        #
        #    **这里不做「对不上就报错」的判断**：判定只交给下面那条
        #    条件 UPDATE（没改到行 -> 409）。两处都判的话，
        #    条件 UPDATE 就变成了摆设——去掉它测试照样全绿，
        #    而它恰恰是并发场景下唯一说了算的那道闸门。
        expected = old_status if expected_status is None else expected_status
        expected_version = _version_token(
            old_updated_at if expected_updated_at is None else expected_updated_at
        )

        new_name = old_name if name is None else name
        new_sort_order = old_sort_order if sort_order is None else sort_order
        new_status = old_status if status is None else status

        # 3) 条件 UPDATE：**闸门只有这一条**。
        #
        #    RETURNING 把落库后的值带回来：审计的 new 值要用它，
        #    而不是请求里那个（请求说 150.5，库里存的是 150.50）。
        result = await session.execute(
            update(ServiceCategory)
            .where(
                ServiceCategory.id == category_id,
                ServiceCategory.status == expected,
                func.date_trunc(VERSION_PRECISION, ServiceCategory.updated_at)
                == expected_version,
            )
            .values(
                name=new_name,
                sort_order=new_sort_order,
                status=new_status,
                # Core 的 UPDATE 不走 ORM 的 onupdate，得自己带上。
                # 用 clock_timestamp()（真实时钟）而不是 now()
                # （事务开始时间）：now() 可能比刚读到的旧值还早，
                # 版本号会往回退，冲突就检测不出来了。
                updated_at=func.clock_timestamp(),
            )
            .returning(
                ServiceCategory.name,
                ServiceCategory.sort_order,
                ServiceCategory.status,
                ServiceCategory.updated_at,
            )
            .execution_options(synchronize_session=False)
        )
        row = result.first()
        if row is None:
            # 谓词没命中：等锁期间被别人改了
            raise PlatformCatalogConflictError(
                CONFLICT_DETAIL.format(target="品类")
            )
        stored_name, stored_sort_order, stored_status, stored_updated_at = row

        # 4) 审计日志：每个真正变了的字段一条。
        #    old 用读到的旧值，new 用**库里落下的值**。
        changes = [
            ("name", old_name, stored_name),
            ("sort_order", old_sort_order, stored_sort_order),
            ("status", old_status.value, stored_status.value),
        ]
        for field_name, old_value, new_value in changes:
            if old_value == new_value:
                continue
            session.add(
                AuditLog(
                    operator_type=operator_type,
                    operator_id=current_user.user_id,
                    target_type=CATEGORY_AUDIT_TARGET_TYPE,
                    target_id=category_id,
                    provider_id=None,
                    field_name=field_name,
                    old_value=_audit_value(old_value),
                    new_value=_audit_value(new_value),
                    reason=CATEGORY_AUDIT_REASON,
                )
            )
        await session.flush()

        updated = PlatformCategory(
            id=old_id,
            name=stored_name,
            parent_id=old_parent_id,
            sort_order=stored_sort_order,
            status=stored_status,
            updated_at=stored_updated_at,
            items=await _items_of_category(session, category_id),
        )

    return updated


# =====================================================================
# 服务项
# =====================================================================


async def create_service_item(
    session: AsyncSession,
    *,
    category_id: int,
    name: str,
    base_price: Decimal,
    duration_min: int,
    current_user: CurrentUser,
) -> PlatformServiceItem:
    """新建一个服务项（初始状态：启用）。

    品类不存在 -> 404（不能把服务项挂在一个不存在的品类下）。
    """
    operator_type = _require_platform_staff(current_user)

    async with session.begin():
        category_exists = (
            await session.execute(
                select(ServiceCategory.id).where(ServiceCategory.id == category_id)
            )
        ).scalar_one_or_none()
        if category_exists is None:
            raise PlatformCatalogNotFoundError(
                CATEGORY_NOT_FOUND_DETAIL.format(category_id=category_id)
            )

        item = ServiceItem(
            category_id=category_id,
            name=name,
            base_price=base_price,
            duration_min=duration_min,
            status=CatalogStatus.ACTIVE,
        )
        session.add(item)
        await session.flush()

        session.add(
            AuditLog(
                operator_type=operator_type,
                operator_id=current_user.user_id,
                target_type=ITEM_AUDIT_TARGET_TYPE,
                target_id=item.id,
                provider_id=None,
                field_name="created",
                old_value=None,
                new_value=name,
                reason=ITEM_CREATE_REASON,
            )
        )
        await session.flush()

        created = PlatformServiceItem(
            id=item.id,
            category_id=item.category_id,
            name=item.name,
            base_price=item.base_price,
            duration_min=item.duration_min,
            status=item.status,
            created_at=item.created_at,
            updated_at=item.updated_at,
        )

    return created


async def update_service_item(
    session: AsyncSession,
    *,
    item_id: int,
    name: str | None = None,
    base_price: Decimal | None = None,
    duration_min: int | None = None,
    status: CatalogStatus | None = None,
    expected_status: CatalogStatus | None = None,
    expected_updated_at: datetime | None = None,
    current_user: CurrentUser,
) -> PlatformServiceItem:
    """改服务项（名称 / 基准价 / 时长 / 状态），返回改完之后的快照。

    **条件 UPDATE**::

        UPDATE service_item SET ...
        WHERE id = :id
          AND status = :期望旧状态
          AND date_trunc('milliseconds', updated_at) = :期望版本号

    一行都没改到 -> 409（这一行已经被别人改过了）。
    服务项不存在 -> 404。

    **价格变更（base_price）必须留痕**：old / new 值都写进 audit_log（R3），
    且 new 值取自 ``UPDATE ... RETURNING``（库里落下的值），不是请求里的值。
    """
    operator_type = _require_platform_staff(current_user)

    async with session.begin():
        old = (
            await session.execute(
                select(
                    ServiceItem.id,
                    ServiceItem.category_id,
                    ServiceItem.name,
                    ServiceItem.base_price,
                    ServiceItem.duration_min,
                    ServiceItem.status,
                    ServiceItem.created_at,
                    ServiceItem.updated_at,
                ).where(ServiceItem.id == item_id)
            )
        ).one_or_none()
        if old is None:
            raise PlatformCatalogNotFoundError(
                ITEM_NOT_FOUND_DETAIL.format(item_id=item_id)
            )
        (
            old_id,
            old_category_id,
            old_name,
            old_base_price,
            old_duration_min,
            old_status,
            old_created_at,
            old_updated_at,
        ) = old

        # 期望旧状态与期望版本号：客户端说它以为的，不说就用刚读到的。
        # 判定同样只交给下面那条条件 UPDATE（没改到行 -> 409）。
        expected = old_status if expected_status is None else expected_status
        expected_version = _version_token(
            old_updated_at if expected_updated_at is None else expected_updated_at
        )

        new_name = old_name if name is None else name
        new_base_price = old_base_price if base_price is None else base_price
        new_duration_min = old_duration_min if duration_min is None else duration_min
        new_status = old_status if status is None else status

        # 条件 UPDATE + RETURNING：闸门只有 WHERE 那几条，
        # 落库后的值靠 RETURNING 带回来（审计的 new 值用真值）。
        result = await session.execute(
            update(ServiceItem)
            .where(
                ServiceItem.id == item_id,
                ServiceItem.status == expected,
                func.date_trunc(VERSION_PRECISION, ServiceItem.updated_at)
                == expected_version,
            )
            .values(
                name=new_name,
                base_price=new_base_price,
                duration_min=new_duration_min,
                status=new_status,
                # clock_timestamp()（真实时钟）而不是 now()（事务开始时间）：
                # now() 可能比刚读到的旧值还早，版本号会往回退。
                updated_at=func.clock_timestamp(),
            )
            .returning(
                ServiceItem.name,
                ServiceItem.base_price,
                ServiceItem.duration_min,
                ServiceItem.status,
                ServiceItem.updated_at,
            )
            .execution_options(synchronize_session=False)
        )
        row = result.first()
        if row is None:
            raise PlatformCatalogConflictError(
                CONFLICT_DETAIL.format(target="服务项")
            )
        (
            stored_name,
            stored_base_price,
            stored_duration_min,
            stored_status,
            stored_updated_at,
        ) = row

        # 审计：old 是读到的旧值，new 是**库里落下的值**。
        changes = [
            ("name", old_name, stored_name),
            ("base_price", old_base_price, stored_base_price),
            ("duration_min", old_duration_min, stored_duration_min),
            ("status", old_status.value, stored_status.value),
        ]
        for field_name, old_value, new_value in changes:
            if old_value == new_value:
                continue
            session.add(
                AuditLog(
                    operator_type=operator_type,
                    operator_id=current_user.user_id,
                    target_type=ITEM_AUDIT_TARGET_TYPE,
                    target_id=item_id,
                    provider_id=None,
                    field_name=field_name,
                    old_value=_audit_value(old_value),
                    new_value=_audit_value(new_value),
                    reason=ITEM_AUDIT_REASON,
                )
            )
        await session.flush()

        updated = PlatformServiceItem(
            id=old_id,
            category_id=old_category_id,
            name=stored_name,
            base_price=stored_base_price,
            duration_min=stored_duration_min,
            status=stored_status,
            created_at=old_created_at,
            updated_at=stored_updated_at,
        )

    return updated


# =====================================================================
# 内部
# =====================================================================


async def _items_of_category(
    session: AsyncSession, category_id: int
) -> list[PlatformServiceItem]:
    """某个品类下的服务项（按 id 升序，含已停用）。"""
    rows = (
        await session.execute(
            select(
                ServiceItem.id,
                ServiceItem.category_id,
                ServiceItem.name,
                ServiceItem.base_price,
                ServiceItem.duration_min,
                ServiceItem.status,
                ServiceItem.created_at,
                ServiceItem.updated_at,
            )
            .where(ServiceItem.category_id == category_id)
            .order_by(ServiceItem.id)
        )
    ).all()
    return [
        PlatformServiceItem(
            id=item_id,
            category_id=item_category_id,
            name=name,
            base_price=base_price,
            duration_min=duration_min,
            status=status,
            created_at=created_at,
            updated_at=updated_at,
        )
        for (
            item_id,
            item_category_id,
            name,
            base_price,
            duration_min,
            status,
            created_at,
            updated_at,
        ) in rows
    ]


def _version_token(value: datetime) -> datetime:
    """把时间戳截到**毫秒**——版本号的精度。

    为什么截到毫秒而不是微秒：前端经过 JS 的 Date 只会剩下毫秒
    （``new Date("...123456Z").toISOString()`` -> ``...123Z``）。
    版本号定得比前端能表达的更细，就会出现「明明没冲突却报 409」。

    没有时区的按 UTC 处理：数据库里存的是带时区的值，
    一个裸时间戳被当成别的时区会平白差出几个小时。
    """
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.replace(microsecond=(value.microsecond // 1000) * 1000)


def _require_platform_staff(current_user: CurrentUser) -> OperatorType:
    """兜底：确认操作人真的是平台侧角色，返回审计用的操作方类型。

    依赖层（``require_platform_staff``）已经保证了这一点，这里再挡一道
    是为了「不变量不只在一个地方保证」——万一哪天依赖被换掉，
    这里会立刻拒，而不是把普通用户的操作写进平台侧的审计日志。
    """
    if current_user.role not in PLATFORM_STAFF_ROLES:
        raise PlatformCatalogForbiddenError("当前角色不能管理目录")
    operator_type = operator_type_for_platform_role(current_user.role)
    if operator_type is None:
        raise PlatformCatalogForbiddenError("当前角色不能管理目录")
    return operator_type


def _audit_value(value: object) -> str:
    """把审计日志里的 old / new 值统一成字符串。

    Decimal 走 ``str()`` 而不是 ``float()``：``float(Decimal('88.00'))``
    会变成 88.0，审计里就看不出「原本是 88.00」了。
    """
    if isinstance(value, Enum):
        return str(value.value)
    return str(value)
