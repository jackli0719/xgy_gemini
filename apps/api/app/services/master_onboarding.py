"""师傅入驻 service：师傅自助登记 + 平台审核。

**这条链路解决的缺口**：入库的 ``UserRole.MASTER`` 账号此前没有任何创建入口
（师傅数据靠手工插库或 seed）。入驻流程把它补上：师傅用手机号登录
（登录即注册，见 app.services.login）拿到普通用户账号 → 提交入驻申请 →
平台审核 → 通过之后这个账号就是师傅。

**流程的两段式**：

1. **登记**（师傅侧）：建一行 ``master``，状态 ``PENDING``（待审核），
   同时把登录账号的角色改成 ``MASTER``。
2. **审核**（平台侧，``PLATFORM_ADMIN``）：``PENDING`` → ``ACTIVE``（通过）
   或删掉这一行（驳回）。

为什么「登记时就把角色改成 MASTER」：师傅身份与登录账号必须**一一对应**
（``uq_master_user_id`` 唯一约束保证一个账号至多一个师傅身份），
角色是这条身份链上的一环。审核状态由 ``master.status`` 单独表达，
两者分工明确——**角色说「你是不是师傅」，status 说「你能不能干活」**。

为什么「驳回是删行」而不是给 master 加一个 REJECTED 状态：

- 枚举值删不掉（PostgreSQL 的 ADD VALUE 只能加不能删），
  而测试库走 ``create_all``、生产走 alembic，加一个枚举值要两条路径同时改
  （见 PROJECT_STATE.md 的技术债）；
- 语义上「没通过审核」就等于**没入职**——不存在一个「已被拒绝的师傅」这种行。
  账号角色回退成 ``USER``，师傅可以改了资料再申请。

**六条硬约束**（每一条都有测试盯着）：

1. **身份只从 token 来**（R1）：师傅身份由 ``current_user.user_id`` 查 master
   表得到，**不从入参取**。申请、查状态两个接口的签名里都没有 user_id /
   master_id 参数——不是「约定别传」，是「传不进来」。
2. **归属校验不暴露存在性**：目标服务商「不存在」与「不是 ACTIVE」
   （待审核 / 已冻结）共用同一个异常、同一句话（404 同构）——
   调用方不该靠报错差异去枚举哪些服务商存在、哪些被冻结。
3. **审核走条件 UPDATE，禁止读-改-写**：
   ``WHERE id = ? AND status = 'PENDING'``。两个平台管理员同时审同一份申请，
   只有一个能成功，另一个拿到 404（同构：申请不存在 / 不在待审核状态）。
   **审核只有平台管理员能做**：依赖层（``require_platform_admin``）之外，
   service 层也挡一道（``_require_platform_admin``）——审核是最重的写操作，
   而审计日志里的 operator_type 记的是「平台管理员」，角色放错审计就撒谎。
4. **留痕**（R3）：登记与审核各写一条 audit_log（target_type='master'、
   field_name='status'、old / new 值、操作人、原因）。
   「谁批的、批给了谁、什么时候」查得到。
   **改判归属另记一条**（field_name='provider_id'）：那条 status 审计的
   provider_id 列填的是改判**之后**的服务商，不单独记一条的话，
   「他原来挂在哪家、被谁改判」就查不到了。
5. **一致性校验**：master 表与 user 表必须对得上——每个 master 行对应一个
   ``role=MASTER`` 且 ``provider_id IS NULL`` 的账号（数据库 CHECK 约束
   ``ck_user_role_provider`` 强制后半句），反过来每个 ``MASTER`` 账号
   恰好有一个 master 行。师傅的归属**只由 master 表说了算**，
   ``user.provider_id`` 对师傅恒为空——service 层显式校验并回读，
   对不上就是服务端数据坏了（500），不装作没这回事。
6. **不接受客户端自报归属**：请求体里没有 provider_id 这个字段。
   师傅申请时填的是 ``target_provider_id``（**申请加入**哪家），
   它是申请内容，不是「当前作用域」；真正的归属由平台审核确认。
   （全仓 openapi 契约测试也禁止请求体出现 provider_id 这个字段名。）

**已知取舍**：服务商把师傅停用（DISABLED）之后，师傅**不能**自己重新申请
——他的 master 行还在，重新申请会被当成「重复申请」挡掉。
离职后重新入职要走平台介入（平台删除该师傅行，或师傅换服务商由平台建行）。
这是刻意的：自助重新申请会绕过服务商的停用决定。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser
from app.core.timezone import now_utc
from app.models.audit_log import AuditLog
from app.models.enums import (
    MasterStatus,
    OnboardingDecision,
    OperatorType,
    ProviderStatus,
    UserRole,
)
from app.models.order import Order
from app.models.provider import Master, ServiceProvider
from app.models.user import User
from app.services.errors import (
    MasterOnboardingConflictError,
    MasterOnboardingForbiddenError,
    MasterOnboardingInvariantError,
    MasterOnboardingNotFoundError,
)

__all__ = [
    "DEFAULT_PAGE_LIMIT",
    "MAX_PAGE_LIMIT",
    "JoinableProvider",
    "OnboardingApplication",
    "OnboardingSubmission",
    "ReviewedApplication",
    "get_my_onboarding",
    "list_joinable_providers",
    "list_onboarding_applications",
    "review_onboarding",
    "submit_onboarding",
]

# 审计日志里的对象类型（审计表用 target_type + target_id 做软关联）
AUDIT_TARGET_TYPE = "master"

# 审计日志里记录的原因
SUBMIT_AUDIT_REASON = "师傅提交入驻申请"
APPROVE_AUDIT_REASON = "平台审核通过师傅入驻申请"
REJECT_AUDIT_REASON = "平台驳回师傅入驻申请"

# 分页口径与平台侧其它列表一致
DEFAULT_PAGE_LIMIT = 20
MAX_PAGE_LIMIT = 100

# 「目标服务商不存在或不可加入」——两种失败共用这一句话。
# 不区分「不存在」与「不是 ACTIVE」：调用方不该靠报错差异枚举服务商名单。
_PROVIDER_NOT_JOINABLE_DETAIL = "服务商不存在或不可加入"

# 「我的入驻申请不存在」
_NO_APPLICATION_DETAIL = "入驻申请不存在"

# 「已经在师傅体系里了」——重复申请的各种情形共用这一句
_ALREADY_ONBOARDED_DETAIL = "已提交过入驻申请或已入职，不能重复申请"

# 「当前账号不能提交入驻申请」
_NOT_APPLICABLE_DETAIL = "当前账号不能提交入驻申请"

# 「入驻申请不存在或不在待审核状态」——两种失败共用这一句（404 同构）
_APPLICATION_NOT_FOUND_DETAIL = "入驻申请不存在或不在待审核状态"

# master 表 user_id 的唯一约束名（见 app.models.provider.UniqueConstraint）
MASTER_USER_CONSTRAINT = "uq_master_user_id"

# 兜底解析约束名：PostgreSQL 的错误消息形如
# duplicate key value violates unique constraint "uq_master_user_id"
_CONSTRAINT_PATTERN = re.compile(r'constraint "([^"]+)"')


@dataclass(frozen=True)
class JoinableProvider:
    """师傅可以申请加入的服务商（只暴露 id 与名称）。

    **不暴露佣金率与联系电话**：那是平台侧 / 服务商侧的信息，
    入驻申请阶段不需要，暴露出去只是多一条泄露渠道。
    """

    id: int
    name: str


@dataclass(frozen=True)
class OnboardingSubmission:
    """刚提交完的入驻申请（快照，标量）。"""

    master_id: int
    real_name: str
    phone: str
    status: MasterStatus
    provider_id: int
    provider_name: str
    created_at: datetime


@dataclass(frozen=True)
class OnboardingApplication:
    """一条入驻申请（平台侧列表 / 师傅自己看的那一条）。"""

    id: int
    real_name: str
    phone: str
    status: MasterStatus
    provider_id: int
    provider_name: str
    created_at: datetime


@dataclass(frozen=True)
class ReviewedApplication:
    """审核完之后的入驻申请。

    ``status`` 为空表示「驳回」——驳回是删行，那一行已经不存在了，
    所以没有状态可回；审核结论记在审计日志里。
    """

    id: int
    real_name: str
    status: MasterStatus | None
    provider_id: int
    provider_name: str
    created_at: datetime


async def list_joinable_providers(
    session: AsyncSession,
) -> list[JoinableProvider]:
    """列出师傅可以申请加入的服务商（只有 ACTIVE 的）。

    按 id 排序（不按状态排序——这里只查 ACTIVE 一种状态，
    但 PostgreSQL 的枚举排序按「取值在类型里的先后」，
    与「业务上想要什么顺序」不是一回事，见 app.models.enums.ProviderStatus）。
    """
    rows = (
        await session.execute(
            select(ServiceProvider.id, ServiceProvider.name)
            .where(ServiceProvider.status == ProviderStatus.ACTIVE)
            .order_by(ServiceProvider.id)
        )
    ).all()
    return [JoinableProvider(id=row.id, name=row.name) for row in rows]


async def submit_onboarding(
    session: AsyncSession,
    *,
    current_user: CurrentUser,
    real_name: str,
    target_provider_id: int,
) -> OnboardingSubmission:
    """提交入驻申请：建师傅行（待审核）+ 把账号角色改成师傅。

    同一事务里做三件事，缺一不可：

    1. 建一行 ``master``（``status=PENDING``、``provider_id=target_provider_id``）；
    2. 把账号角色改成 ``MASTER``（师傅身份与登录账号一一对应）；
    3. 写一条 audit_log（谁、什么时候、投了哪家）。

    失败语义：

    - 角色不是普通用户（服务商账号 / 平台账号）-> 403；
    - 已经是师傅 / 已经申请过 -> 409；
    - 目标服务商不存在或不是 ACTIVE -> 404（同构，不暴露服务商名单）；
    - 并发提交（两个请求同时建师傅行）-> 409（撞 ``uq_master_user_id``）。

    **角色以库里的为准，不以 token 里的为准**：token 是登录那一刻签的，
    可能已经过期（申请成功后账号角色变成 MASTER，旧 token 里还写着 USER）。
    所以真正的判定在事务里读 user 表做（``_resolve_applicant_role``），
    token 里的角色只用来快速挡掉「压根不该来申请」的那些账号。
    """
    if current_user.role not in (UserRole.USER, UserRole.MASTER):
        # 服务商账号、平台账号都不该来申请入驻。
        # 在碰库之前就挡住：角色不对的账号连「能不能申请」都问不到。
        raise MasterOnboardingForbiddenError(_NOT_APPLICABLE_DETAIL)

    # 目标服务商必须是「可以加入」的那一种（ACTIVE）。
    # 不存在与「不是 ACTIVE」共用一句话，调用方不该靠报错差异
    # 去枚举哪些服务商存在、哪些被冻结。
    #
    # 这一步在事务**里面**做：读一次就会把 session 的 autobegin 事务开起来，
    # 后面再 `session.begin()` 就会因为「已有活动事务」报错。
    async with session.begin():
        provider = await _resolve_joinable_provider(session, target_provider_id)

        # 申请人的真实角色（库里那份，不是 token 里那份）
        applicant_role, phone = await _resolve_applicant_role(
            session, current_user.user_id
        )
        if applicant_role is UserRole.MASTER:
            # 已经是师傅了：要么审核通过了，要么正在审核中
            raise MasterOnboardingConflictError(_ALREADY_ONBOARDED_DETAIL)
        if applicant_role is not UserRole.USER:
            # 角色在登录之后被改成了别的（服务商 / 平台账号）
            raise MasterOnboardingForbiddenError(_NOT_APPLICABLE_DETAIL)

        # 这个账号是不是已经有师傅身份了？
        #
        # **有就不许再申请**：审核中的（PENDING）、已入职的
        # （ACTIVE / ON_LEAVE）、在服务商处被停用的（DISABLED）都挡掉。
        # 最后一种是刻意的：自助重新申请会绕过服务商的停用决定。
        existing = await _find_existing_master(session, current_user.user_id)
        if existing is not None:
            raise MasterOnboardingConflictError(_ALREADY_ONBOARDED_DETAIL)

        now = now_utc()
        try:
            master = Master(
                provider_id=provider.id,
                user_id=current_user.user_id,
                real_name=real_name,
                # 登记一律「待审核」：能不能入职由平台说了算，
                # 状态**不由请求体决定**
                status=MasterStatus.PENDING,
            )
            session.add(master)
            await session.flush()

            # 账号角色改成 MASTER。
            #
            # 条件 UPDATE（``WHERE id = ? AND role = 'USER'``）：
            # 「这个账号还是普通用户」写进谓词，判定交给行锁裁决。
            # role=MASTER 的 provider_id 必须为空（数据库 CHECK 约束
            # ck_user_role_provider 强制），这里不写 provider_id 就是对的。
            role_result = await session.execute(
                update(User)
                .where(User.id == current_user.user_id, User.role == UserRole.USER)
                .values(role=UserRole.MASTER, updated_at=now)
            )
            if role_result.rowcount != 1:
                # 角色已经不是 USER 了：要么被别人并发改过，
                # 要么这个账号压根不是普通用户。两种都是服务端状态变了，
                # 客户端重试前先刷新。
                raise MasterOnboardingConflictError(_ALREADY_ONBOARDED_DETAIL)

            session.add(
                AuditLog(
                    operator_type=OperatorType.USER,
                    operator_id=current_user.user_id,
                    target_type=AUDIT_TARGET_TYPE,
                    target_id=master.id,
                    provider_id=provider.id,
                    field_name="status",
                    # 新建的师傅行之前没有状态 -> old_value 为空
                    old_value=None,
                    new_value=MasterStatus.PENDING.value,
                    reason=SUBMIT_AUDIT_REASON,
                )
            )
            await session.flush()
        except IntegrityError as exc:
            # 并发提交：两个请求同时建师傅行，后者撞 uq_master_user_id。
            # 只认这一种冲突——别的完整性冲突说明数据有问题，原样抛出去。
            if not _is_master_user_unique_violation(exc):
                raise
            raise MasterOnboardingConflictError(_ALREADY_ONBOARDED_DETAIL) from None

        # 回读校验：本事务写出来的样子必须与库里一致。
        # 对不上就是服务端 bug（500），不能装作成功。
        await _assert_identity_consistent(
            session, user_id=current_user.user_id, master_id=master.id
        )

        # 快照在事务**里面**取：commit 之后 ORM 对象可能已过期，
        # 那时再访问属性会触发一次隐式加载（async 下直接炸）。
        snapshot = OnboardingSubmission(
            master_id=master.id,
            real_name=master.real_name,
            phone=phone,
            status=master.status,
            provider_id=provider.id,
            provider_name=provider.name,
            created_at=master.created_at,
        )

    return snapshot


async def get_my_onboarding(
    session: AsyncSession, *, current_user: CurrentUser
) -> OnboardingApplication:
    """返回当前账号的入驻申请（没有申请 -> 404）。

    身份只从 token 来：按 ``current_user.user_id`` 查 master 表，
    不接收任何 id 入参。
    """
    row = (
        await session.execute(
            select(
                Master.id,
                Master.real_name,
                Master.status,
                Master.provider_id,
                ServiceProvider.name,
                User.phone,
                Master.created_at,
            )
            .join(ServiceProvider, ServiceProvider.id == Master.provider_id)
            .join(User, User.id == Master.user_id)
            .where(Master.user_id == current_user.user_id)
        )
    ).one_or_none()
    if row is None:
        raise MasterOnboardingNotFoundError(_NO_APPLICATION_DETAIL)
    return OnboardingApplication(
        id=row.id,
        real_name=row.real_name,
        phone=row.phone,
        status=row.status,
        provider_id=row.provider_id,
        provider_name=row.name,
        created_at=row.created_at,
    )


async def list_onboarding_applications(
    session: AsyncSession,
    *,
    status: MasterStatus | None = None,
    page: int = 1,
    limit: int = DEFAULT_PAGE_LIMIT,
) -> tuple[list[OnboardingApplication], int]:
    """平台侧：列出入驻申请（默认只看待审核的）。

    按 id 排序（入库顺序就是登记顺序），不做「按状态排序」——
    PostgreSQL 的枚举排序按取值在类型里的先后，不是业务顺序。
    """
    effective_page = max(page, 1)
    effective_limit = min(max(limit, 1), MAX_PAGE_LIMIT)

    scope = []
    if status is not None:
        scope.append(Master.status == status)

    total = (
        await session.execute(
            select(func.count()).select_from(Master).where(*scope)
        )
    ).scalar_one()

    rows = (
        await session.execute(
            select(
                Master.id,
                Master.real_name,
                Master.status,
                Master.provider_id,
                ServiceProvider.name,
                User.phone,
                Master.created_at,
            )
            .join(ServiceProvider, ServiceProvider.id == Master.provider_id)
            .join(User, User.id == Master.user_id)
            .where(*scope)
            .order_by(Master.id)
            .offset((effective_page - 1) * effective_limit)
            .limit(effective_limit)
        )
    ).all()
    return [
        OnboardingApplication(
            id=row.id,
            real_name=row.real_name,
            phone=row.phone,
            status=row.status,
            provider_id=row.provider_id,
            provider_name=row.name,
            created_at=row.created_at,
        )
        for row in rows
    ], total


async def review_onboarding(
    session: AsyncSession,
    *,
    current_user: CurrentUser,
    master_id: int,
    decision: OnboardingDecision | str,
    target_provider_id: int | None = None,
    reason: str | None = None,
) -> ReviewedApplication:
    """平台审核一份入驻申请：通过（转 ACTIVE）或驳回（删行、角色回退）。

    **判定走条件 UPDATE**（通过时）：

    ``WHERE id = ? AND status = 'PENDING'``。

    两个平台管理员同时审同一份申请，只有一个能成功；
    另一个拿到 404（「申请不存在或不在待审核状态」——同构，
    不告诉调用方「它刚被别人审过了」）。

    通过时可以改判服务商：传了 ``target_provider_id`` 就改挂到那家，
    不传就沿用申请里选的那家。改判目标必须是 ACTIVE 的服务商，
    否则 404（与「不存在」同构）。

    驳回是**删行 + 账号角色回退 USER**：没通过审核就等于没入职，
    师傅改了资料可以再申请（``uq_master_user_id`` 也就不会挡住第二次申请）。

    要求传入的 session 没有活动事务——本函数会自行管理事务生命周期。
    """
    _require_platform_admin(current_user)
    resolved = _resolve_decision(decision)

    async with session.begin():
        # 先把这一行读出来：为了拿到 provider_id / real_name / created_at
        # 回给调用方，也为了知道「驳回时要不要删」。
        #
        # **判定仍然交给下面的条件 UPDATE / DELETE**：这一步读到的是快照，
        # 等锁期间状态可能已经被别人改了（ABA），所以真正的裁决在谓词里。
        row = await _load_application(session, master_id)
        if row is None:
            raise MasterOnboardingNotFoundError(_APPLICATION_NOT_FOUND_DETAIL)
        if row.status is not MasterStatus.PENDING:
            # 不是待审核的申请（已审过 / 已入职 / 已被停用）：
            # 与「不存在」是同一件事 -> 404 同构。
            #
            # 早退还有一层好处：不对已入职的师傅做后面的检查
            # （比如「他名下有没有订单」），也不给他写任何东西。
            raise MasterOnboardingNotFoundError(_APPLICATION_NOT_FOUND_DETAIL)

        if resolved is OnboardingDecision.APPROVE:
            provider = await _resolve_joinable_provider(
                session,
                target_provider_id
                if target_provider_id is not None
                else row.provider_id,
            )
            now = now_utc()
            # 条件 UPDATE：只有还在「待审核」的申请才改得动。
            result = await session.execute(
                update(Master)
                .where(Master.id == master_id, Master.status == MasterStatus.PENDING)
                .values(status=MasterStatus.ACTIVE, provider_id=provider.id, updated_at=now)
                .returning(Master.id)
            )
            if result.first() is None:
                # 申请不存在（上面已排除）/ 状态不是 PENDING /
                # 等锁期间被别人审过了：三种情况对调用方是同一件事
                raise MasterOnboardingNotFoundError(_APPLICATION_NOT_FOUND_DETAIL)

            session.add(
                AuditLog(
                    operator_type=OperatorType.PLATFORM_ADMIN,
                    operator_id=current_user.user_id,
                    target_type=AUDIT_TARGET_TYPE,
                    target_id=master_id,
                    provider_id=provider.id,
                    field_name="status",
                    old_value=row.status.value,
                    new_value=MasterStatus.ACTIVE.value,
                    reason=reason or APPROVE_AUDIT_REASON,
                )
            )
            if provider.id != row.provider_id:
                # 改判归属也要留痕：master.provider_id 决定这位师傅归谁、
                # 他的订单佣金算给谁。上面那条 audit_log 的 provider_id 列
                # 填的是**改判之后**的服务商，不单独记一条的话，
                # 「他原来挂在哪家、被谁改判」就查不到了（旧服务商那边查不到）。
                session.add(
                    AuditLog(
                        operator_type=OperatorType.PLATFORM_ADMIN,
                        operator_id=current_user.user_id,
                        target_type=AUDIT_TARGET_TYPE,
                        target_id=master_id,
                        provider_id=provider.id,
                        field_name="provider_id",
                        old_value=str(row.provider_id),
                        new_value=str(provider.id),
                        reason=reason or APPROVE_AUDIT_REASON,
                    )
                )
            await session.flush()

            await _assert_identity_consistent(
                session, user_id=row.user_id, master_id=master_id
            )

            provider_name = provider.name
            new_status: MasterStatus | None = MasterStatus.ACTIVE
            provider_id = provider.id
        else:
            # 驳回：删掉这一行，账号角色回退成普通用户。
            #
            # 删之前先确认这个师傅没有订单——正常流程下不可能有
            # （被驳回的是还没入职的师傅），有的话说明数据坏了。
            order_count = (
                await session.execute(
                    select(func.count())
                    .select_from(Order)
                    .where(Order.master_id == master_id)
                )
            ).scalar_one()
            if order_count:
                # 服务端数据坏了：待审核的师傅却有订单。暴露成 500，
                # 不能悄悄把有订单的师傅删掉。
                raise MasterOnboardingInvariantError(
                    "待审核的师傅却有订单，删除会留下悬空引用：master_id={}".format(
                        master_id
                    )
                )

            now = now_utc()
            # 条件 DELETE：只有还在「待审核」的申请才删得动
            delete_result = await session.execute(
                delete(Master).where(
                    Master.id == master_id,
                    Master.status == MasterStatus.PENDING,
                    Master.user_id == row.user_id,
                )
            )
            if delete_result.rowcount != 1:
                raise MasterOnboardingNotFoundError(_APPLICATION_NOT_FOUND_DETAIL)

            # 角色回退：条件 UPDATE（``WHERE id = ? AND role = 'MASTER'``）
            role_result = await session.execute(
                update(User)
                .where(User.id == row.user_id, User.role == UserRole.MASTER)
                .values(role=UserRole.USER, updated_at=now)
            )
            if role_result.rowcount != 1:
                raise MasterOnboardingInvariantError(
                    "师傅身份与登录账号对不上：master_id={}".format(master_id)
                )

            session.add(
                AuditLog(
                    operator_type=OperatorType.PLATFORM_ADMIN,
                    operator_id=current_user.user_id,
                    target_type=AUDIT_TARGET_TYPE,
                    target_id=master_id,
                    provider_id=row.provider_id,
                    field_name="status",
                    old_value=row.status.value,
                    # 驳回不是「某个状态」，是「没有这个师傅了」：
                    # new_value 记 REJECTED，删行才是事实
                    new_value="REJECTED",
                    reason=reason or REJECT_AUDIT_REASON,
                )
            )
            await session.flush()

            provider_name = row.name
            new_status = None
            provider_id = row.provider_id

        # 快照在事务**里面**取：commit 之后 ORM 对象可能已过期，
        # 那时再访问属性会触发一次隐式加载（async 下直接炸）。
        snapshot = ReviewedApplication(
            id=master_id,
            real_name=row.real_name,
            status=new_status,
            provider_id=provider_id,
            provider_name=provider_name,
            created_at=row.created_at,
        )

    return snapshot


async def _find_existing_master(
    session: AsyncSession, user_id: int
) -> tuple[int, MasterStatus] | None:
    """查这个账号已有的师傅身份（没有就返回 None）。

    单独抽成一个函数，是为了让并发测试能在这里放会合点
    （会合点必须落在「实现第一次碰到 master 表的位置」，
    见 tests/support.py 的说明）。
    """
    row = (
        await session.execute(
            select(Master.id, Master.status).where(Master.user_id == user_id)
        )
    ).one_or_none()
    if row is None:
        return None
    return row.id, row.status


async def _load_application(
    session: AsyncSession, master_id: int
):
    """读出要审核的那份入驻申请（连同服务商名称）。

    同样单独抽出来：并发审核测试的会合点放在这里。

    **这一步不做判定**：改不改得动由后面的条件 UPDATE 说了算。
    """
    row = (
        await session.execute(
            select(
                Master.id,
                Master.real_name,
                Master.status,
                Master.provider_id,
                Master.user_id,
                Master.created_at,
                ServiceProvider.name,
            )
            .join(ServiceProvider, ServiceProvider.id == Master.provider_id)
            .where(Master.id == master_id)
        )
    ).one_or_none()
    return row


async def _resolve_applicant_role(
    session: AsyncSession, user_id: int
) -> tuple[UserRole, str]:
    """读出申请人在**库里**的角色与手机号。

    为什么不信 token：token 是登录那一刻签的，可能已经过期
    （申请成功后账号角色变成 MASTER，旧 token 里还写着 USER）。
    库里那份才是当前事实。

    账号不存在 -> 409（token 有效但账号没了，属于状态冲突：
    刷新登录会拿到新的失败原因）。
    """
    row = (
        await session.execute(
            select(User.role, User.phone).where(User.id == user_id)
        )
    ).one_or_none()
    if row is None:
        raise MasterOnboardingConflictError("账号不存在")
    return row.role, row.phone


async def _resolve_joinable_provider(
    session: AsyncSession, provider_id: int
) -> ServiceProvider:
    """取出「可以加入」的服务商；不行就 404（同构）。

    只有 ACTIVE 的服务商可以加入：待审核的（PENDING）还没开业，
    被冻结的（FROZEN）不能接新单——让师傅去投奔一家不能接单的店，
    审核通过也派不了单。
    """
    provider = (
        await session.execute(
            select(ServiceProvider).where(
                ServiceProvider.id == provider_id,
                ServiceProvider.status == ProviderStatus.ACTIVE,
            )
        )
    ).scalar_one_or_none()
    if provider is None:
        raise MasterOnboardingNotFoundError(_PROVIDER_NOT_JOINABLE_DETAIL)
    return provider


async def _assert_identity_consistent(
    session: AsyncSession, *, user_id: int, master_id: int
) -> None:
    """校验「师傅身份 ↔ 登录账号」这一对关系是自洽的。

    规则（与数据库 CHECK 约束 ``ck_user_role_provider`` 同口径）：

    - 账号角色是 ``MASTER``；
    - 账号的 ``provider_id`` **为空**——师傅的归属只由 master 表说了算，
      ``user.provider_id`` 记的是**登录账号**的服务商归属，两回事。

    对不上就是服务端数据坏了（500），不装作没这回事。
    """
    row = (
        await session.execute(
            select(User.role, User.provider_id).where(User.id == user_id)
        )
    ).one_or_none()
    if row is None:
        raise MasterOnboardingInvariantError(
            "师傅的登录账号不存在：user_id={}".format(user_id)
        )
    if row.role is not UserRole.MASTER:
        raise MasterOnboardingInvariantError(
            "师傅身份与登录账号角色对不上：user_id={} role={}".format(
                user_id, row.role
            )
        )
    if row.provider_id is not None:
        raise MasterOnboardingInvariantError(
            "师傅账号不该带服务商归属：user_id={} provider_id={}".format(
                user_id, row.provider_id
            )
        )

    master_exists = (
        await session.execute(
            select(Master.id).where(Master.id == master_id, Master.user_id == user_id)
        )
    ).first()
    if master_exists is None:
        raise MasterOnboardingInvariantError(
            "师傅身份与登录账号对不上：master_id={} user_id={}".format(
                master_id, user_id
            )
        )


def _require_platform_admin(current_user: CurrentUser) -> None:
    """兜底：确认操作人真的是平台管理员。

    依赖层（``require_platform_admin``）已经保证这一点，这里再挡一道
    是为了「不变量不只在一个地方保证」——万一哪天依赖被换掉，
    这里会立刻拒，而不是把审核权放给不该有它的人
    （与 app.services.platform_provider._require_platform_admin、
    app.services.settle._require_finance_role 同一套写法）。

    **为什么这道门重要**：审核是这条链路上最重的写操作（把师傅置成
    已入职、改判他的归属、驳回时删行并回退账号角色），
    而审计日志里的 operator_type 记的是「平台管理员」。
    角色一旦放错，审计就会谎报操作人身份，R3 的追溯当场失效。
    """
    if current_user.role is not UserRole.PLATFORM_ADMIN:
        raise MasterOnboardingForbiddenError("当前角色不能审核入驻申请")


def _resolve_decision(decision: OnboardingDecision | str) -> OnboardingDecision:
    """把审核结论收敛成 ``OnboardingDecision``。

    **为什么要在这里再挡一次**：接口层用窄枚举把非法值变成 422，
    但那道防线只在「走接口」时有效——service 也会被直接调用
    （测试、将来的定时任务、别的入口），那时类型提示挡不住运行时传错值。

    所以这里按同一份事实来源（``app.models.enums.OnboardingDecision``）
    显式校验一遍：非法结论连数据都不该看一眼。
    """
    value = decision.value if isinstance(decision, Enum) else str(decision)
    try:
        return OnboardingDecision(value)
    except ValueError:
        raise MasterOnboardingForbiddenError(
            "入驻审核结论只能是 APPROVE 或 REJECT，收到：{}".format(value)
        ) from None


def _is_master_user_unique_violation(exc: IntegrityError) -> bool:
    """判断这个完整性冲突是不是 ``uq_master_user_id`` 撞了。"""
    orig = getattr(exc, "orig", None)
    constraint = getattr(orig, "constraint_name", None)
    if constraint is None:
        match = _CONSTRAINT_PATTERN.search(str(exc))
        constraint = match.group(1) if match else None
    return constraint == MASTER_USER_CONSTRAINT
