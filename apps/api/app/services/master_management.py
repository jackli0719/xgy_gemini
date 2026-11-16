"""服务商侧师傅管理 service：改本商师傅的状态。

服务商后台要能停用一个师傅（休假 / 离职），或把他重新启用。
这条链路只做一件事：**把本商师傅的 status 改成指定值**。

四条硬约束（每一条都有测试盯着）：

1. **provider_id 只从 CurrentUser 取**，函数签名里根本没有 provider_id 这个
   参数——不是「约定别传」，是「传不进来」。租户归属一旦能由客户端指定，
   隔离当场失效（R1）。请求体里带 provider_id 会被 schema 直接 422。
2. **归属校验不暴露存在性**：师傅不属于本服务商、或这个师傅根本不存在，
   与「这个资源不存在」抛同一个异常、同一句话。调用方没法靠报错差异
   探测别家有没有这个人（与派单是同一套语义、同一句文案，见
   app.services.provider_scope）。
3. **归属判定：读旧状态时也按归属过滤，条件 UPDATE 里再带一次**。
   读那一步的谓词是 ``WHERE id = ? AND provider_id = ?``——别家的师傅
   （或者压根不存在的 id）读不到，于是 404，两种情况同构。
   UPDATE 那一步再带一次归属：读到的只是快照，等锁期间这一行可能已被
   别人改走，谓词不成立就一条也没改到（rowcount == 0 -> 404）。
   **为什么不能只靠 UPDATE 那一道**：本模块还要判断「这个师傅是不是
   正在待审核」（待审核的师傅不许服务商改状态，见下），
   而入驻登记之后 PENDING 的师傅是**全平台存在**的（申请人自选服务商）。
   若旧状态读取不按归属过滤，别家待审核的师傅会在这里被认出并返回 409，
   别家已入职的师傅却返回 404——两种响应可区分，就成了跨租户的状态
   oracle（R1）。所以归属先判定完，再谈状态。
4. **状态变更必须留痕**：同事务内写一条 audit_log
   （target_type='master'、field_name='status'、old / new 值、操作人）。
   谁能改师傅状态、把它从什么状态改成什么状态，必须查得到（R3）。

**归属校验与派单共用同一套异常与文案**（``MasterNotFoundError``）：
「这个师傅不在本商」在派单和师傅管理上是同一件事，
两个接口的 404 长得不一样会让客户端以为有两种错误。

**师傅入驻不在本模块**：PENDING（待审核）是入驻流程的初始状态，
由平台侧的入驻卡产生；服务商只能把师傅置为 ACTIVE / ON_LEAVE / DISABLED。
这条规则由 ``app.models.enums.SettableMasterStatus`` 表达（**事实来源**），
接口层用它把 PENDING 变成 422，service 用它把不合法的状态挡在库外——
两道防线共用同一份定义，不会各写各的。

**待审核（PENDING）的师傅，服务商侧一个字都改不了**：
入职状态只能由平台审核流转（见 app.services.master_onboarding.review_onboarding）。
服务商提前把待审核的师傅置成 ACTIVE，等于绕过平台审核那道闸门——
派单那头会真的把单派给他（T-13 审查发现的绕过路径）。
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser
from app.models.audit_log import AuditLog
from app.models.enums import MasterStatus, SettableMasterStatus
from app.models.provider import Master
from app.models.user import User
from app.services.errors import (
    DispatchForbiddenError,
    MasterNotFoundError,
    MasterPendingNotSettableError,
    MasterStatusNotSettableError,
)
from app.services.provider_scope import (
    MASTER_NOT_FOUND_DETAIL,
    operator_type_for_provider_role,
)

__all__ = ["ManagedMaster", "update_master_status"]

# 审计日志里的对象类型（审计表用 target_type + target_id 做软关联）
AUDIT_TARGET_TYPE = "master"

# 审计日志里记录的原因
AUDIT_REASON = "服务商调整师傅状态"

# 允许被设置的师傅状态（事实来源：app.models.enums.SettableMasterStatus）
_SETTABLE_STATUS_VALUES = frozenset(s.value for s in SettableMasterStatus)

# 「待审核的师傅不能由服务商改状态」的文案
_PENDING_MASTER_DETAIL = "待审核的师傅由平台审核流转，服务商不能改他的状态"


@dataclass(frozen=True)
class ManagedMaster:
    """被改过状态的那位师傅（改完之后的快照）。"""

    id: int
    real_name: str
    phone: str
    rating: Decimal | None
    status: MasterStatus


async def update_master_status(
    session: AsyncSession,
    *,
    master_id: int,
    status: SettableMasterStatus | MasterStatus,
    current_user: CurrentUser,
) -> ManagedMaster:
    """把本商师傅改成指定状态，返回改完之后的师傅。

    ``status`` 的类型声明是 ``SettableMasterStatus``（允许设置的那几个），
    但**运行时还会再挡一次**：类型提示挡不住有人传 ``MasterStatus.PENDING``
    进来（直接调 service 的路径绕过了接口层的窄枚举）。
    详见 ``_resolve_settable_status``。

    事务：取旧值、条件 UPDATE、写审计日志、回读展示字段在同一事务内，
    要么全成要么全不成。

    要求传入的 session 没有活动事务——本函数会自行管理事务生命周期。
    """
    provider_id = current_user.provider_id
    if provider_id is None:
        # 没有服务商归属就没有「本商」可言，直接拒绝，不碰数据
        raise DispatchForbiddenError("当前账号没有服务商归属，不能管理师傅")

    operator_type = operator_type_for_provider_role(current_user.role)
    if operator_type is None:
        # 走到这里说明依赖被换掉了：不是服务商侧角色也放进了来
        raise DispatchForbiddenError("当前角色不能管理师傅")

    # 状态校验放在碰库之前：不合法的状态连数据都不该看一眼
    new_status = _resolve_settable_status(status)

    async with session.begin():
        # 1) 旧状态（审计日志要记 old_value）+ **归属判定**。
        #
        # 这一步**按归属过滤**：``Master.id = ? AND Master.provider_id = ?``。
        # 读不到 -> 这个师傅不在本商名下（或者压根不存在）-> 404，
        # 两种情况共用同一句话，调用方没法靠报错差异探测别家有没有这个人
        # （R1）。
        #
        # **为什么归属判定要在这里也做一遍**（下面那条条件 UPDATE 里还有一遍）：
        # 「待审核（PENDING）的师傅不许改」这条规则需要知道
        # 「这个师傅在本商名下、而且正在待审核」。如果这一步不按归属过滤，
        # 别家（甚至别平台）的待审核师傅会在这里被识别出来并返回 409，
        # 而别家已入职的师傅走到下面那条 UPDATE 才返回 404——
        # 两种响应可区分，就成了跨租户的存在性 / 状态 oracle。
        # 所以归属判定先做完，再谈状态。
        #
        # 并发下这个旧值可能稍旧（两个管理员同时改一个师傅时，
        # 两条审计都记同一个旧值）。真正生效的状态以 UPDATE 为准，
        # 审计里 old/new 的用途是「看得出改了什么」，不是精确到并发的流水。
        old_status = (
            await session.execute(
                select(Master.status).where(
                    Master.id == master_id,
                    Master.provider_id == provider_id,
                )
            )
        ).scalar_one_or_none()
        if old_status is None:
            # 不在本商名下，或者这个 id 上根本没有师傅：两种情况同构
            raise MasterNotFoundError(
                MASTER_NOT_FOUND_DETAIL.format(master_id=master_id)
            )
        if old_status is MasterStatus.PENDING:
            # 待审核的师傅不能由服务商改状态。
            #
            # PENDING 是**入驻流程**的状态，只能由平台审核流转
            # （见 app.services.master_onboarding.review_onboarding）：
            # 服务商提前把他置成 ACTIVE，等于绕过平台审核那道闸门；
            # 置成 DISABLED / ON_LEAVE 也不对——这位师傅还没入职，
            # 服务商根本不该动他的入职状态。
            #
            # 到这一步说明归属已经成立（本商的师傅），所以回 409
            # 不会泄露别家的信息。
            raise MasterPendingNotSettableError(_PENDING_MASTER_DETAIL)

        # 2) 条件 UPDATE：**并发裁决的闸门**。
        #
        # 谓词里再带一次归属：上面那步的读只是快照，等锁期间
        # 这一行可能已被别人改走（甚至被划到别家名下）。
        # 谓词不成立 -> 一条也没改到 -> rowcount == 0 -> 404。
        # 与派单同一套思路——把判定交给数据库，不靠读-改-写。
        result = await session.execute(
            update(Master)
            .where(
                Master.id == master_id,
                Master.provider_id == provider_id,
            )
            .values(
                status=new_status,
                # Core 的 UPDATE 不走 ORM 的 onupdate，得自己带上
                updated_at=func.now(),
            )
        )
        if result.rowcount != 1:
            # 别家的师傅（「不存在」在第 1 步就返回了）
            raise MasterNotFoundError(
                MASTER_NOT_FOUND_DETAIL.format(master_id=master_id)
            )

        # 3) 审计日志：状态变更留痕（R3）。
        # 操作方记**真实角色**：管理员记 PROVIDER_ADMIN、员工记 PROVIDER_STAFF。
        session.add(
            AuditLog(
                operator_type=operator_type,
                operator_id=current_user.user_id,
                target_type=AUDIT_TARGET_TYPE,
                target_id=master_id,
                provider_id=provider_id,
                field_name="status",
                old_value=old_status.value,
                new_value=new_status.value,
                reason=AUDIT_REASON,
            )
        )
        await session.flush()

        # 4) 回读展示字段。这一步**按归属过滤**：只读自己那一行。
        row = (
            await session.execute(
                select(
                    Master.id,
                    Master.real_name,
                    Master.rating,
                    Master.status,
                    User.phone,
                )
                .join(User, User.id == Master.user_id)
                .where(
                    Master.id == master_id,
                    Master.provider_id == provider_id,
                )
            )
        ).one()

    return ManagedMaster(
        id=row.id,
        real_name=row.real_name,
        phone=row.phone,
        rating=row.rating,
        status=row.status,
    )


def _resolve_settable_status(
    status: SettableMasterStatus | MasterStatus,
) -> MasterStatus:
    """把传入的状态收敛成「允许被设置」的 ``MasterStatus``。

    **为什么要在这里再挡一次**：接口层用窄枚举（``SettableMasterStatus``）
    把 PENDING 变成 422，但那条防线只在「走接口」时有效。service 也会被
    直接调用（测试、将来的别的入口），那时类型提示挡不住运行时传错值——
    ``MasterStatus.PENDING`` 照样能传进来。

    所以这里按同一份事实来源（``app.models.enums.SettableMasterStatus``）
    显式校验一遍：不在可设置集合里就抛业务异常，而不是照单全收。
    """
    value = status.value if isinstance(status, Enum) else str(status)
    if value not in _SETTABLE_STATUS_VALUES:
        raise MasterStatusNotSettableError(
            "师傅状态不允许被设置为：{}".format(value)
        )
    return MasterStatus(value)
