"""平台侧服务商管理 service（PLAT-01）。

平台侧管的是**所有**服务商：建档、审核、冻结、给服务商建管理员账号。

与服务商侧链路的根本区别：**「管哪一个」是请求的一部分**（路径里的
provider_id），但**「我是谁」永远只从 token 来**（CurrentUser）。
客户端能说「我要改 3 号服务商」，但不能自报「我是平台管理员」。

四条硬约束（每一条都有测试盯着）：

1. **operator 只从 CurrentUser 取**：函数签名里没有 operator 参数，
   审计日志里的操作人由服务端从 token 里的 role / user_id 填，
   请求体里出现 operator 之类字段会被 schema 直接 422。
2. **改状态用条件 UPDATE，禁止读-改-写**：
   ``WHERE id = ? AND status IN (允许的旧状态)``。
   判定交给数据库的行锁裁决——两个平台管理员同时点「审核通过」，
   只有一个能成功，另一个拿到 409，而不是两边都以为改成功了。
   读旧状态（审计要用）因此**不是**判定依据：读到旧值只用来写审计，
   改不改得动由 UPDATE 说了算。
3. **状态变更必须留痕**：同事务内写一条 audit_log
   （target_type='service_provider'、field_name='status'、old / new 值、
   操作人）。建档与建管理员账号同样留痕。
4. **手机号唯一**：建管理员时手机号已被占用 -> 409「手机号已注册」，
   不泄露「这个手机号是谁的」。
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser
from app.models.audit_log import AuditLog
from app.models.enums import OperatorType, ProviderStatus, SettableProviderStatus, UserRole
from app.models.provider import ServiceProvider
from app.models.user import User
from app.services.errors import (
    PlatformProviderConflictError,
    PlatformProviderForbiddenError,
    PlatformProviderNotFoundError,
    PlatformProviderStatusNotSettableError,
)

__all__ = [
    "DEFAULT_PAGE_LIMIT",
    "MAX_PAGE_LIMIT",
    "PlatformProvider",
    "ProviderAdmin",
    "create_provider",
    "create_provider_admin",
    "list_providers",
    "update_provider_status",
]

logger = logging.getLogger(__name__)

# 审计日志里的对象类型（审计表用 target_type + target_id 做软关联）
AUDIT_TARGET_TYPE = "service_provider"

# 审计日志里记录的原因
AUDIT_REASON = "平台调整服务商状态"
CREATE_AUDIT_REASON = "平台创建服务商"
ADMIN_AUDIT_REASON = "平台创建服务商管理员账号"

# user 表 phone 的唯一约束名（见 app.models.user 的 UniqueConstraint）
USER_PHONE_CONSTRAINT = "uq_user_phone"

# 分页默认值与上限
DEFAULT_PAGE_LIMIT = 20
MAX_PAGE_LIMIT = 100

# 「手机号已注册」——两种触发路径（先查重 / 撞唯一约束）共用这一句话，
# 不泄露「这个手机号已经是谁的」。
PHONE_TAKEN_DETAIL = "手机号已注册"

# 「服务商不存在」
PROVIDER_NOT_FOUND_DETAIL = "服务商不存在：provider_id={provider_id}"

# 「这个状态不允许这么改」
STATUS_CONFLICT_DETAIL = "服务商当前状态不允许改成 {new_status}"

# 「这个目标状态压根不许设置」（PENDING / 废弃取值）
STATUS_NOT_SETTABLE_DETAIL = "服务商状态不允许被设置为：{new_status}"


@dataclass(frozen=True)
class PlatformProvider:
    """服务商的一条快照（标量，不持有 ORM 对象）。"""

    id: int
    name: str
    contact_phone: str
    commission_rate: Decimal
    status: ProviderStatus
    created_at: datetime


@dataclass(frozen=True)
class ProviderAdmin:
    """刚建出来的服务商管理员账号。"""

    id: int
    phone: str
    role: UserRole
    provider_id: int
    created_at: datetime


# 目标状态 -> 允许的旧状态。
#
# 「审核通过」与「解冻」的目标都是 ACTIVE，来源分别是 PENDING / FROZEN；
# 「冻结」只能从 ACTIVE 来。
#
# 这张表是**状态机的事实来源**：条件 UPDATE 的谓词直接用它
# （``status IN (...)``），接口层与 service 层都不另写一份。
_ALLOWED_SOURCE_STATUSES: dict[ProviderStatus, frozenset[ProviderStatus]] = {
    ProviderStatus.ACTIVE: frozenset({ProviderStatus.PENDING, ProviderStatus.FROZEN}),
    ProviderStatus.FROZEN: frozenset({ProviderStatus.ACTIVE}),
}


async def list_providers(
    session: AsyncSession,
    *,
    status: ProviderStatus | None = None,
    page: int = 1,
    limit: int = DEFAULT_PAGE_LIMIT,
) -> tuple[list[PlatformProvider], int]:
    """列出服务商（一页 + 总数）。

    ``status`` 传 None 表示不按状态过滤（平台侧要看全部）。
    **排序按 id**，不按 status：PostgreSQL 的枚举排序按「取值在类型里
    的先后」来，而 create_all 建的库与 alembic 建的库取值顺序不一样
    （迁移 0007 是往已有类型上追加取值），按 status 排序会让两条建库
    路径给出不同的顺序。按 id 排则两边一致。
    """
    page = max(page, 1)
    limit = min(max(limit, 1), MAX_PAGE_LIMIT)

    conditions = []
    if status is not None:
        conditions.append(ServiceProvider.status == status)

    count_stmt = select(func.count()).select_from(ServiceProvider)
    if conditions:
        count_stmt = count_stmt.where(*conditions)
    total = (await session.execute(count_stmt)).scalar_one()

    stmt = select(
        ServiceProvider.id,
        ServiceProvider.name,
        ServiceProvider.contact_phone,
        ServiceProvider.commission_rate,
        ServiceProvider.status,
        ServiceProvider.created_at,
    )
    if conditions:
        stmt = stmt.where(*conditions)
    stmt = stmt.order_by(ServiceProvider.id).offset((page - 1) * limit).limit(limit)

    rows = (await session.execute(stmt)).all()
    providers = [
        PlatformProvider(
            id=row.id,
            name=row.name,
            contact_phone=row.contact_phone,
            commission_rate=row.commission_rate,
            status=row.status,
            created_at=row.created_at,
        )
        for row in rows
    ]
    return providers, total


async def create_provider(
    session: AsyncSession,
    *,
    name: str,
    contact_phone: str,
    commission_rate: Decimal,
    current_user: CurrentUser,
) -> PlatformProvider:
    """建一个服务商，初始状态「待审核」（PENDING）。

    状态**不由请求体决定**：新建一律待审核，要审核通过再调改状态接口。
    那样「审核」这一步才真的存在——默认放行等于没有审核。
    """
    _require_platform_admin(current_user)

    async with session.begin():
        provider = ServiceProvider(
            name=name,
            contact_phone=contact_phone,
            commission_rate=commission_rate,
            status=ProviderStatus.PENDING,
        )
        session.add(provider)
        await session.flush()

        session.add(
            AuditLog(
                operator_type=OperatorType.PLATFORM_ADMIN,
                operator_id=current_user.user_id,
                target_type=AUDIT_TARGET_TYPE,
                target_id=provider.id,
                provider_id=provider.id,
                field_name="created",
                old_value=None,
                new_value=ProviderStatus.PENDING.value,
                reason=CREATE_AUDIT_REASON,
            )
        )
        await session.flush()

        created_at = provider.created_at

    return PlatformProvider(
        id=provider.id,
        name=provider.name,
        contact_phone=provider.contact_phone,
        commission_rate=provider.commission_rate,
        status=provider.status,
        created_at=created_at,
    )


async def update_provider_status(
    session: AsyncSession,
    *,
    provider_id: int,
    status: SettableProviderStatus | ProviderStatus,
    current_user: CurrentUser,
) -> PlatformProvider:
    """把服务商改成指定状态，返回改完之后的快照。

    **条件 UPDATE**（不是读-改-写）::

        UPDATE service_provider SET status = :new
        WHERE id = :id AND status IN (:允许的旧状态)

    rowcount == 0 -> 409：当前状态不允许这次流转，或者等锁期间状态被别人改了。
    两个平台管理员同时点「审核通过」时，只有一个能成功。
    """
    _require_platform_admin(current_user)

    new_status = _resolve_settable_status(status)
    allowed_sources = _ALLOWED_SOURCE_STATUSES[new_status]

    async with session.begin():
        # 1) 旧状态：只用来写审计，**不作为判定依据**。
        #    （与 app.services.master_management 同一思路：判定交给 UPDATE。）
        old_status = (
            await session.execute(
                select(ServiceProvider.status).where(ServiceProvider.id == provider_id)
            )
        ).scalar_one_or_none()
        if old_status is None:
            raise PlatformProviderNotFoundError(
                PROVIDER_NOT_FOUND_DETAIL.format(provider_id=provider_id)
            )

        # 2) 条件 UPDATE：**闸门只有这一条**。
        result = await session.execute(
            update(ServiceProvider)
            .where(
                ServiceProvider.id == provider_id,
                ServiceProvider.status.in_(allowed_sources),
            )
            .values(
                status=new_status,
                # Core 的 UPDATE 不走 ORM 的 onupdate，得自己带上
                updated_at=func.now(),
            )
        )
        if result.rowcount != 1:
            # 当前状态不允许这次流转（或被别人抢先改了）
            raise PlatformProviderConflictError(
                STATUS_CONFLICT_DETAIL.format(new_status=new_status.value)
            )

        # 3) 审计日志：状态变更留痕（R3）。
        session.add(
            AuditLog(
                operator_type=OperatorType.PLATFORM_ADMIN,
                operator_id=current_user.user_id,
                target_type=AUDIT_TARGET_TYPE,
                target_id=provider_id,
                provider_id=provider_id,
                field_name="status",
                old_value=old_status.value,
                new_value=new_status.value,
                reason=AUDIT_REASON,
            )
        )
        await session.flush()

        # 4) 回读展示字段。
        row = (
            await session.execute(
                select(
                    ServiceProvider.id,
                    ServiceProvider.name,
                    ServiceProvider.contact_phone,
                    ServiceProvider.commission_rate,
                    ServiceProvider.status,
                    ServiceProvider.created_at,
                ).where(ServiceProvider.id == provider_id)
            )
        ).one()

    return PlatformProvider(
        id=row.id,
        name=row.name,
        contact_phone=row.contact_phone,
        commission_rate=row.commission_rate,
        status=row.status,
        created_at=row.created_at,
    )


async def create_provider_admin(
    session: AsyncSession,
    *,
    provider_id: int,
    phone: str,
    current_user: CurrentUser,
) -> ProviderAdmin:
    """给某个服务商建一个管理员账号（role=PROVIDER_ADMIN）。

    **角色与归属都由服务端填**：客户端只给手机号。
    归属来自路径里的 provider_id（平台侧本来就要管所有服务商），
    角色是固定的 PROVIDER_ADMIN——客户端不能自选角色
    （不然就能给自己造一个 PROVIDER_ADMIN 或 PLATFORM_ADMIN）。

    手机号已被占用 -> 409「手机号已注册」。
    """
    _require_platform_admin(current_user)

    async with session.begin():
        exists = (
            await session.execute(
                select(ServiceProvider.id).where(ServiceProvider.id == provider_id)
            )
        ).scalar_one_or_none()
        if exists is None:
            raise PlatformProviderNotFoundError(
                PROVIDER_NOT_FOUND_DETAIL.format(provider_id=provider_id)
            )

        taken = (
            await session.execute(select(User.id).where(User.phone == phone))
        ).scalar_one_or_none()
        if taken is not None:
            raise PlatformProviderConflictError(PHONE_TAKEN_DETAIL)

        user = User(
            phone=phone,
            nickname="管理员{}".format(phone[-4:]),
            role=UserRole.PROVIDER_ADMIN,
            provider_id=provider_id,
        )
        session.add(user)
        try:
            await session.flush()
        except IntegrityError as exc:
            # 并发建号：另一个请求刚把这个手机号建好了。
            # 只认 phone 唯一约束这一种冲突，别的是数据有问题，原样抛出去。
            if not _is_phone_unique_violation(exc):
                raise
            raise PlatformProviderConflictError(PHONE_TAKEN_DETAIL) from exc

        session.add(
            AuditLog(
                operator_type=OperatorType.PLATFORM_ADMIN,
                operator_id=current_user.user_id,
                target_type=AUDIT_TARGET_TYPE,
                target_id=provider_id,
                provider_id=provider_id,
                field_name="admin_created",
                old_value=None,
                new_value=phone,
                reason=ADMIN_AUDIT_REASON,
            )
        )
        await session.flush()

        created_at = user.created_at

    return ProviderAdmin(
        id=user.id,
        phone=user.phone,
        role=user.role,
        provider_id=user.provider_id,
        created_at=created_at,
    )


def _require_platform_admin(current_user: CurrentUser) -> None:
    """兜底：确认操作人真的是平台管理员。

    依赖层（``require_platform_admin``）已经保证了这一点，这里再挡一道
    是为了「不变量不只在一个地方保证」——万一哪天依赖被换掉，
    这里会立刻拒，而不是把一个普通用户的操作写进平台侧的审计日志。
    """
    if current_user.role is not UserRole.PLATFORM_ADMIN:
        raise PlatformProviderForbiddenError("当前角色不能管理服务商")


def _resolve_settable_status(
    status: SettableProviderStatus | ProviderStatus,
) -> ProviderStatus:
    """把传入的状态收敛成「允许被设置」的 ``ProviderStatus``。

    **为什么要在这里再挡一次**：接口层用窄枚举（``SettableProviderStatus``）
    把 PENDING / 两个废弃取值变成 422，但那条防线只在「走接口」时有效。
    service 也会被直接调用（测试、将来的别的入口），那时类型提示挡不住
    运行时传错值——``ProviderStatus.PENDING`` 照样能传进来。
    """
    value = status.value if isinstance(status, Enum) else str(status)
    try:
        resolved = ProviderStatus(value)
    except ValueError:
        raise PlatformProviderStatusNotSettableError(
            STATUS_NOT_SETTABLE_DETAIL.format(new_status=value)
        ) from None
    if resolved not in _ALLOWED_SOURCE_STATUSES:
        raise PlatformProviderStatusNotSettableError(
            STATUS_NOT_SETTABLE_DETAIL.format(new_status=resolved.value)
        )
    return resolved


def _is_phone_unique_violation(exc: IntegrityError) -> bool:
    """判断这个完整性冲突是不是 phone 唯一约束（uq_user_phone）撞了。"""
    orig = getattr(exc, "orig", None)
    constraint = getattr(orig, "constraint_name", None)
    if constraint is None:
        # 驱动没给约束名时从消息里兜底解析
        match = re.search(r'constraint "([^"]+)"', str(exc))
        constraint = match.group(1) if match else None
    return constraint == USER_PHONE_CONSTRAINT
