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
3. **归属的闸门只有一条：那条条件 UPDATE**。
   ``WHERE id = ? AND provider_id = ?``——别家的师傅 UPDATE 命中 0 行，
   于是 404。**不先查出来再判断**：那样会把归属校验拆成两处（查询一处、
   UPDATE 一处），少写一处就是「改到别家的人」；而且 UPDATE 里的归属条件
   会变成摆设——去掉它也没人看得出来。
   查询旧状态（审计要用）因此**不按归属过滤**：它只是取一个旧值，
   改不改得动由 UPDATE 说了算。
4. **状态变更必须留痕**：同事务内写一条 audit_log
   （target_type='master'、field_name='status'、old / new 值、操作人）。
   谁能改师傅状态、把它从什么状态改成什么状态，必须查得到（R3）。

**归属校验与派单共用同一套异常与文案**（``MasterNotFoundError``）：
「这个师傅不在本商」在派单和师傅管理上是同一件事，
两个接口的 404 长得不一样会让客户端以为有两种错误。

**师傅入驻不在本模块**：PENDING（待审核）是入驻流程的初始状态，
由平台侧的入驻卡产生；服务商只能把师傅置为 ACTIVE / ON_LEAVE / DISABLED。
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser
from app.models.audit_log import AuditLog
from app.models.enums import MasterStatus
from app.models.provider import Master
from app.models.user import User
from app.services.errors import DispatchForbiddenError, MasterNotFoundError
from app.services.provider_scope import (
    MASTER_NOT_FOUND_DETAIL,
    operator_type_for_provider_role,
)

__all__ = ["ManagedMaster", "update_master_status"]

# 审计日志里的对象类型（审计表用 target_type + target_id 做软关联）
AUDIT_TARGET_TYPE = "master"

# 审计日志里记录的原因
AUDIT_REASON = "服务商调整师傅状态"


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
    status: MasterStatus,
    current_user: CurrentUser,
) -> ManagedMaster:
    """把本商师傅改成指定状态，返回改完之后的师傅。

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

    async with session.begin():
        # 1) 旧状态（审计日志要记 old_value）。
        #
        # 这一步**不按归属过滤**：它只负责取一个旧值，
        # 「这个师傅能不能改」由下面那条条件 UPDATE 说了算。
        #
        # 并发下这个旧值可能稍旧（两个管理员同时改一个师傅时，
        # 两条审计都记同一个旧值）。真正生效的状态以 UPDATE 为准，
        # 审计里 old/new 的用途是「看得出改了什么」，不是精确到并发的流水。
        old_status = (
            await session.execute(
                select(Master.status).where(Master.id == master_id)
            )
        ).scalar_one_or_none()
        if old_status is None:
            # 这个 id 上根本没有师傅
            raise MasterNotFoundError(
                MASTER_NOT_FOUND_DETAIL.format(master_id=master_id)
            )

        # 2) 条件 UPDATE：**归属的闸门只有这一条**。
        #
        # 别家的师傅：谓词不成立，一条也没改到 -> rowcount == 0 -> 404。
        # 与派单同一套思路——把判定交给数据库，不靠读-改-写。
        result = await session.execute(
            update(Master)
            .where(
                Master.id == master_id,
                Master.provider_id == provider_id,
            )
            .values(
                status=status,
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
                new_value=status.value,
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
