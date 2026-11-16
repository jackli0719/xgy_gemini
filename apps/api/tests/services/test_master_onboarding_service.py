"""师傅入驻 service 的测试（登记申请 / 平台审核）。

必测点：

1. **登记**：建 master 行（PENDING）+ 账号角色改成 MASTER + audit_log 留痕；
2. **归属不暴露**：目标服务商「不存在」与「不是 ACTIVE」共用同一个异常、
   同一句话（404 同构）；
3. **不重复申请**：审核中 / 已入职 / 被服务商停用 -> 409；
4. **角色守卫**：服务商账号、平台账号 -> 403；
5. **审核**：条件 UPDATE（并发只有一个能过）、改判服务商、驳回删行 + 角色回退；
6. **一致性**：master 表与 user 表必须对得上（角色 MASTER、provider_id 为空、
   一一对应）——这是 T-09a-0 记下来的技术债，本卡补上校验与测试；
7. **并发**：两个请求同时登记 / 同时审核，只能有一个成功。

集成测试用的数据库是 TEST_DATABASE_URL 指向的独立测试库
（集成 fixture 每次 drop_all + create_all，绝不碰开发库）。
"""
from __future__ import annotations

import asyncio
import os
from decimal import Decimal

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.auth import CurrentUser
from app.models.address import Address
from app.models.audit_log import AuditLog
from app.models.base import Base
from app.models.catalog import ServiceCategory, ServiceItem
from app.models.enums import (
    MasterStatus,
    OperatorType,
    OrderStatus,
    PayStatus,
    ProviderStatus,
    UserRole,
)
from app.models.order import Order
from app.models.provider import Master, ServiceProvider
from app.models.schedule_slot import ScheduleSlot
from app.models.user import User
from app.services import master_onboarding
from app.services.errors import (
    MasterOnboardingConflictError,
    MasterOnboardingForbiddenError,
    MasterOnboardingInvariantError,
    MasterOnboardingNotFoundError,
)
from tests.support import Rendezvous, business_today

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


@pytest.fixture
async def db():
    """每个集成测试一块干净的库。"""
    if not TEST_DATABASE_URL:
        pytest.skip("需要真实 PostgreSQL：请设置 TEST_DATABASE_URL")
    engine = create_async_engine(
        TEST_DATABASE_URL,
        pool_size=25,
        max_overflow=25,
        pool_pre_ping=True,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
async def maker(db):
    """会话工厂（每个 service 调用自己管事务，所以要各自的 session）。"""
    return async_sessionmaker(db, class_=AsyncSession, expire_on_commit=False)


async def _seed(maker) -> dict[str, int]:
    """造数据：三种状态的服务商 + 各类账号 + 已有师傅身份。

    **不显式指定 id**：让数据库序列自己分配（显式写 id 会让序列停在 1，
    后面新建的行拿到 id=1 撞车）。id 一律从落库对象上取。
    """
    async with maker() as session:
        provider_active = ServiceProvider(
            name="甲服务商",
            contact_phone="13900000001",
            status=ProviderStatus.ACTIVE,
        )
        provider_active_b = ServiceProvider(
            name="乙服务商",
            contact_phone="13900000004",
            status=ProviderStatus.ACTIVE,
        )
        provider_pending = ServiceProvider(
            name="待审服务商",
            contact_phone="13900000002",
            status=ProviderStatus.PENDING,
        )
        provider_frozen = ServiceProvider(
            name="冻结服务商",
            contact_phone="13900000003",
            status=ProviderStatus.FROZEN,
        )
        session.add_all(
            [provider_active, provider_active_b, provider_pending, provider_frozen]
        )
        await session.flush()

        plain_user = User(phone="13800000001", nickname="普通用户")
        provider_admin = User(
            phone="13800000002",
            nickname="甲管理员",
            role=UserRole.PROVIDER_ADMIN,
            provider_id=provider_active.id,
        )
        platform_admin = User(
            phone="13800000003",
            nickname="平台管理员",
            role=UserRole.PLATFORM_ADMIN,
        )
        # 已经是师傅的账号（角色 MASTER，provider_id 恒空）
        active_master_user = User(
            phone="13800000004",
            nickname="已入职师傅",
            role=UserRole.MASTER,
        )
        # 审核中的师傅
        pending_master_user = User(
            phone="13800000005",
            nickname="审核中师傅",
            role=UserRole.MASTER,
        )
        # 被服务商停用的师傅（DISABLED）：不能自助重新申请
        disabled_master_user = User(
            phone="13800000006",
            nickname="被停用师傅",
            role=UserRole.MASTER,
        )
        session.add_all(
            [
                plain_user,
                provider_admin,
                platform_admin,
                active_master_user,
                pending_master_user,
                disabled_master_user,
            ]
        )
        await session.flush()

        active_master = Master(
            provider_id=provider_active.id,
            user_id=active_master_user.id,
            real_name="已入职师傅",
            status=MasterStatus.ACTIVE,
            rating=Decimal("4.5"),
        )
        pending_master = Master(
            provider_id=provider_active.id,
            user_id=pending_master_user.id,
            real_name="审核中师傅",
            status=MasterStatus.PENDING,
        )
        disabled_master = Master(
            provider_id=provider_active.id,
            user_id=disabled_master_user.id,
            real_name="被停用师傅",
            status=MasterStatus.DISABLED,
        )
        session.add_all([active_master, pending_master, disabled_master])
        await session.flush()
        await session.commit()

        return {
            "provider_active": provider_active.id,
            "provider_active_b": provider_active_b.id,
            "provider_pending": provider_pending.id,
            "provider_frozen": provider_frozen.id,
            "plain_user": plain_user.id,
            "provider_admin": provider_admin.id,
            "platform_admin": platform_admin.id,
            "active_master_user": active_master_user.id,
            "pending_master_user": pending_master_user.id,
            "disabled_master_user": disabled_master_user.id,
            "active_master": active_master.id,
            "pending_master": pending_master.id,
            "disabled_master": disabled_master.id,
        }


async def _seed_order_for(maker, *, master_id: int) -> None:
    """造一笔指向某个师傅的订单（外键链：品类 -> 服务项 -> 时段 + 地址）。

    只为测「有订单的师傅不能被删」那一条用。
    """
    from datetime import time

    async with maker() as session:
        category = ServiceCategory(name="保洁")
        session.add(category)
        await session.flush()
        item = ServiceItem(
            category_id=category.id,
            name="日常保洁",
            base_price=Decimal("100.00"),
            duration_min=60,
        )
        session.add(item)
        await session.flush()
        address = Address(
            user_id=1,
            contact="张三",
            phone="13900000009",
            region="北京",
            detail="某街道 1 号",
        )
        session.add(address)
        await session.flush()
        slot = ScheduleSlot(
            item_id=item.id,
            date=business_today(),
            start_time=time(9, 0),
            end_time=time(12, 0),
            capacity=5,
        )
        session.add(slot)
        await session.flush()
        session.add(
            Order(
                order_no="OTO20260101000001",
                user_id=address.user_id,
                provider_id=None,
                master_id=master_id,
                address_id=address.id,
                item_id=item.id,
                slot_id=slot.id,
                amount=Decimal("100.00"),
                status=OrderStatus.PENDING_ACCEPT,
                pay_status=PayStatus.PAID,
            )
        )
        await session.flush()
        await session.commit()


def _current(user_id: int, role: UserRole = UserRole.USER) -> CurrentUser:
    """造一个当前用户（师傅账号的 provider_id 恒空）。"""
    provider_id = None
    if role in (UserRole.PROVIDER_ADMIN, UserRole.PROVIDER_STAFF):
        raise AssertionError("服务商账号要自己带 provider_id")
    return CurrentUser(user_id=user_id, role=role, provider_id=provider_id)


# =====================================================================
# 单元测试：审核结论的收敛
# =====================================================================


def test_resolve_decision_accepts_enum_and_string() -> None:
    """审核结论两种写法都认（枚举 / 字符串）。"""
    from app.models.enums import OnboardingDecision

    assert (
        master_onboarding._resolve_decision(OnboardingDecision.APPROVE)
        is OnboardingDecision.APPROVE
    )
    assert (
        master_onboarding._resolve_decision("REJECT") is OnboardingDecision.REJECT
    )


def test_resolve_decision_rejects_unknown_value() -> None:
    """非法结论连数据都不该看一眼。"""
    with pytest.raises(MasterOnboardingForbiddenError):
        master_onboarding._resolve_decision("MAYBE")


# =====================================================================
# 登记申请
# =====================================================================


@pytest.mark.integration
async def test_submit_creates_pending_master_and_promotes_role(maker, db) -> None:
    """登记成功：master 行 PENDING + 账号角色变 MASTER + 归属写对。"""
    seeded = await _seed(maker)
    current = _current(seeded["plain_user"])

    async with maker() as session:
        submission = await master_onboarding.submit_onboarding(
            session,
            current_user=current,
            real_name="张师傅",
            target_provider_id=seeded["provider_active"],
        )

    assert submission.status is MasterStatus.PENDING
    assert submission.real_name == "张师傅"
    assert submission.provider_id == seeded["provider_active"]
    assert submission.provider_name == "甲服务商"
    assert submission.phone == "13800000001"

    async with maker() as session:
        master = (
            await session.execute(
                select(Master).where(Master.id == submission.master_id)
            )
        ).scalar_one()
        user = (
            await session.execute(select(User).where(User.id == seeded["plain_user"]))
        ).scalar_one()

    assert master.status is MasterStatus.PENDING
    assert master.provider_id == seeded["provider_active"]
    assert master.user_id == seeded["plain_user"]
    # 角色改了，但 provider_id 恒空（师傅的归属只由 master 表说了算）
    assert user.role is UserRole.MASTER
    assert user.provider_id is None


@pytest.mark.integration
async def test_submit_writes_audit_log(maker, db) -> None:
    """登记留痕：谁、什么时候、投了哪家，都能查得到。"""
    seeded = await _seed(maker)
    current = _current(seeded["plain_user"])

    async with maker() as session:
        submission = await master_onboarding.submit_onboarding(
            session,
            current_user=current,
            real_name="李师傅",
            target_provider_id=seeded["provider_active"],
        )

    async with maker() as session:
        logs = (
            await session.execute(
                select(AuditLog).where(
                    AuditLog.target_type == "master",
                    AuditLog.target_id == submission.master_id,
                )
            )
        ).scalars().all()

    assert len(logs) == 1
    log = logs[0]
    assert log.operator_type is OperatorType.USER
    assert log.operator_id == seeded["plain_user"]
    assert log.field_name == "status"
    assert log.old_value is None
    assert log.new_value == MasterStatus.PENDING.value
    assert log.reason == "师傅提交入驻申请"
    assert log.provider_id == seeded["provider_active"]


@pytest.mark.integration
async def test_submit_to_missing_provider_is_404(maker, db) -> None:
    """目标服务商不存在 -> 404。"""
    seeded = await _seed(maker)
    current = _current(seeded["plain_user"])

    async with maker() as session:
        with pytest.raises(MasterOnboardingNotFoundError) as excinfo:
            await master_onboarding.submit_onboarding(
                session,
                current_user=current,
                real_name="张师傅",
                target_provider_id=999999,
            )

    assert "服务商不存在或不可加入" in str(excinfo.value)


@pytest.mark.integration
async def test_submit_to_non_active_provider_is_404_same_message(
    maker, db
) -> None:
    """目标服务商不是 ACTIVE（待审 / 冻结）-> 与「不存在」逐字同构。

    不区分「不存在」与「被冻结」：调用方不该靠报错差异枚举服务商的名单。
    """
    seeded = await _seed(maker)
    current = _current(seeded["plain_user"])

    messages = []
    for provider_id in (seeded["provider_pending"], seeded["provider_frozen"]):
        async with maker() as session:
            with pytest.raises(MasterOnboardingNotFoundError) as excinfo:
                await master_onboarding.submit_onboarding(
                    session,
                    current_user=current,
                    real_name="张师傅",
                    target_provider_id=provider_id,
                )
        messages.append(str(excinfo.value))

    async with maker() as session:
        with pytest.raises(MasterOnboardingNotFoundError) as excinfo:
            await master_onboarding.submit_onboarding(
                session,
                current_user=current,
                real_name="张师傅",
                target_provider_id=999999,
            )
    messages.append(str(excinfo.value))

    assert len(set(messages)) == 1, messages


@pytest.mark.integration
async def test_submit_twice_is_409(maker, db) -> None:
    """重复申请 -> 409（不产生第二份申请）。"""
    seeded = await _seed(maker)
    current = _current(seeded["plain_user"])

    async with maker() as session:
        await master_onboarding.submit_onboarding(
            session,
            current_user=current,
            real_name="张师傅",
            target_provider_id=seeded["provider_active"],
        )

    async with maker() as session:
        with pytest.raises(MasterOnboardingConflictError):
            await master_onboarding.submit_onboarding(
                session,
                current_user=current,
                real_name="张师傅",
                target_provider_id=seeded["provider_active"],
            )

    async with maker() as session:
        count = (
            await session.execute(
                select(func.count()).select_from(Master).where(
                    Master.user_id == seeded["plain_user"]
                )
            )
        ).scalar_one()
    assert count == 1


@pytest.mark.integration
async def test_submit_when_already_active_is_409(maker, db) -> None:
    """已入职的师傅不能再申请。"""
    seeded = await _seed(maker)
    current = _current(seeded["active_master_user"], UserRole.MASTER)

    async with maker() as session:
        with pytest.raises(MasterOnboardingConflictError):
            await master_onboarding.submit_onboarding(
                session,
                current_user=current,
                real_name="已入职师傅",
                target_provider_id=seeded["provider_active"],
            )


@pytest.mark.integration
async def test_submit_when_disabled_by_provider_is_409(maker, db) -> None:
    """被服务商停用的师傅不能自助重新申请。

    刻意如此：自助重新申请会绕过服务商的停用决定。
    """
    seeded = await _seed(maker)
    current = _current(seeded["disabled_master_user"], UserRole.MASTER)

    async with maker() as session:
        with pytest.raises(MasterOnboardingConflictError):
            await master_onboarding.submit_onboarding(
                session,
                current_user=current,
                real_name="被停用师傅",
                target_provider_id=seeded["provider_active"],
            )


@pytest.mark.integration
async def test_submit_with_provider_role_is_403(maker, db) -> None:
    """服务商账号 / 平台账号 -> 403（在碰库之前就挡住）。"""
    seeded = await _seed(maker)

    for user_id, role in (
        (seeded["provider_admin"], UserRole.PROVIDER_ADMIN),
        (seeded["platform_admin"], UserRole.PLATFORM_ADMIN),
    ):
        current = CurrentUser(
            user_id=user_id,
            role=role,
            provider_id=seeded["provider_active"]
            if role is UserRole.PROVIDER_ADMIN
            else None,
        )
        async with maker() as session:
            with pytest.raises(MasterOnboardingForbiddenError):
                await master_onboarding.submit_onboarding(
                    session,
                    current_user=current,
                    real_name="张师傅",
                    target_provider_id=seeded["provider_active"],
                )


@pytest.mark.integration
async def test_submit_fails_when_role_changed_concurrently(
    maker, db, monkeypatch
) -> None:
    """登记途中账号角色被别人改了 -> 409，不许覆盖别人的角色。

    模拟「快照过期」：读角色那一步返回的是普通用户，
    而库里此刻这个账号已经被改成别的角色了。
    角色 UPDATE 的谓词（``AND role='USER'``）就是为这种情况准备的：
    谓词不成立 -> 改 0 行 -> 409，而不是把别人的角色覆盖掉。
    """
    seeded = await _seed(maker)

    async with maker() as session:
        await session.execute(
            update(User)
            .where(User.id == seeded["plain_user"])
            .values(role=UserRole.PLATFORM_ADMIN)
        )
        await session.commit()

    async def _stale_role(session, user_id):
        # 快照：这一步读到的是「普通用户」
        return UserRole.USER, "13800000001"

    monkeypatch.setattr(
        master_onboarding, "_resolve_applicant_role", _stale_role
    )

    async with maker() as session:
        with pytest.raises(MasterOnboardingConflictError):
            await master_onboarding.submit_onboarding(
                session,
                current_user=_current(seeded["plain_user"]),
                real_name="张师傅",
                target_provider_id=seeded["provider_active"],
            )

    async with maker() as session:
        user = (
            await session.execute(select(User).where(User.id == seeded["plain_user"]))
        ).scalar_one()
    # 角色没有被覆盖
    assert user.role is UserRole.PLATFORM_ADMIN


# =====================================================================
# 平台审核
# =====================================================================


@pytest.mark.integration
async def test_review_approve_activates_and_logs(maker, db) -> None:
    """审核通过：状态转 ACTIVE + audit_log 留痕。"""
    seeded = await _seed(maker)
    platform = _current(seeded["platform_admin"], UserRole.PLATFORM_ADMIN)

    async with maker() as session:
        reviewed = await master_onboarding.review_onboarding(
            session,
            current_user=platform,
            master_id=seeded["pending_master"],
            decision="APPROVE",
        )

    assert reviewed.status is MasterStatus.ACTIVE

    async with maker() as session:
        master = (
            await session.execute(
                select(Master).where(Master.id == seeded["pending_master"])
            )
        ).scalar_one()
        logs = (
            await session.execute(
                select(AuditLog).where(
                    AuditLog.target_type == "master",
                    AuditLog.target_id == seeded["pending_master"],
                )
            )
        ).scalars().all()

    assert master.status is MasterStatus.ACTIVE
    assert len(logs) == 1
    assert logs[0].operator_type is OperatorType.PLATFORM_ADMIN
    assert logs[0].old_value == MasterStatus.PENDING.value
    assert logs[0].new_value == MasterStatus.ACTIVE.value


@pytest.mark.integration
async def test_review_can_reassign_provider(maker, db) -> None:
    """审核时可以改判服务商：挂到另一家去。"""
    seeded = await _seed(maker)
    platform = _current(seeded["platform_admin"], UserRole.PLATFORM_ADMIN)

    async with maker() as session:
        reviewed = await master_onboarding.review_onboarding(
            session,
            current_user=platform,
            master_id=seeded["pending_master"],
            decision="APPROVE",
            target_provider_id=seeded["provider_active_b"],
        )

    assert reviewed.provider_id == seeded["provider_active_b"]
    async with maker() as session:
        master = (
            await session.execute(
                select(Master).where(Master.id == seeded["pending_master"])
            )
        ).scalar_one()
    assert master.provider_id == seeded["provider_active_b"]


@pytest.mark.integration
async def test_review_reject_deletes_row_and_restores_role(maker, db) -> None:
    """驳回：删行 + 账号角色回退成普通用户（没通过审核 = 没入职）。"""
    seeded = await _seed(maker)
    platform = _current(seeded["platform_admin"], UserRole.PLATFORM_ADMIN)

    async with maker() as session:
        reviewed = await master_onboarding.review_onboarding(
            session,
            current_user=platform,
            master_id=seeded["pending_master"],
            decision="REJECT",
            reason="资质不齐",
        )

    assert reviewed.status is None

    async with maker() as session:
        master = (
            await session.execute(
                select(Master).where(Master.id == seeded["pending_master"])
            )
        ).scalar_one_or_none()
        user = (
            await session.execute(
                select(User).where(User.id == seeded["pending_master_user"])
            )
        ).scalar_one()
        logs = (
            await session.execute(
                select(AuditLog).where(
                    AuditLog.target_type == "master",
                    AuditLog.target_id == seeded["pending_master"],
                )
            )
        ).scalars().all()

    assert master is None
    assert user.role is UserRole.USER
    assert len(logs) == 1
    assert logs[0].new_value == "REJECTED"
    assert logs[0].reason == "资质不齐"


@pytest.mark.integration
async def test_review_requires_platform_admin(maker, db) -> None:
    """审核只有平台管理员能做（service 层也挡一道）。

    依赖层已经挡住了 HTTP 这条路，这里守的是「service 可能被别处
    直接调用」那条路——角色放错，审计里的 operator_type 就会谎报操作人。
    """
    seeded = await _seed(maker)

    for role, provider_id in (
        (UserRole.USER, None),
        (UserRole.PROVIDER_ADMIN, seeded["provider_active"]),
    ):
        current = CurrentUser(
            user_id=seeded["plain_user"], role=role, provider_id=provider_id
        )
        async with maker() as session:
            with pytest.raises(MasterOnboardingForbiddenError):
                await master_onboarding.review_onboarding(
                    session,
                    current_user=current,
                    master_id=seeded["pending_master"],
                    decision="APPROVE",
                )


@pytest.mark.integration
async def test_review_reassignment_writes_provider_audit(maker, db) -> None:
    """改判归属要单独留一条审计：原来挂在哪家、被谁改判，查得到。"""
    seeded = await _seed(maker)
    platform = _current(seeded["platform_admin"], UserRole.PLATFORM_ADMIN)

    async with maker() as session:
        await master_onboarding.review_onboarding(
            session,
            current_user=platform,
            master_id=seeded["pending_master"],
            decision="APPROVE",
            target_provider_id=seeded["provider_active_b"],
        )

    async with maker() as session:
        logs = (
            await session.execute(
                select(AuditLog).where(
                    AuditLog.target_type == "master",
                    AuditLog.target_id == seeded["pending_master"],
                )
            )
        ).scalars().all()

    by_field = {log.field_name: log for log in logs}
    assert set(by_field) == {"status", "provider_id"}
    reassign = by_field["provider_id"]
    assert reassign.old_value == str(seeded["provider_active"])
    assert reassign.new_value == str(seeded["provider_active_b"])
    assert reassign.operator_type is OperatorType.PLATFORM_ADMIN


@pytest.mark.integration
async def test_review_unknown_application_is_404(maker, db) -> None:
    """审核不存在的申请 -> 404。"""
    seeded = await _seed(maker)
    platform = _current(seeded["platform_admin"], UserRole.PLATFORM_ADMIN)

    async with maker() as session:
        with pytest.raises(MasterOnboardingNotFoundError):
            await master_onboarding.review_onboarding(
                session,
                current_user=platform,
                master_id=999999,
                decision="APPROVE",
            )


@pytest.mark.integration
async def test_review_twice_is_404_same_as_missing(maker, db) -> None:
    """已审过的申请再审 -> 404，且与「不存在」逐字同构。

    不告诉调用方「它刚被别人审过了」——两种情况长得一样。
    """
    seeded = await _seed(maker)
    platform = _current(seeded["platform_admin"], UserRole.PLATFORM_ADMIN)

    async with maker() as session:
        await master_onboarding.review_onboarding(
            session,
            current_user=platform,
            master_id=seeded["pending_master"],
            decision="APPROVE",
        )

    async with maker() as session:
        with pytest.raises(MasterOnboardingNotFoundError) as twice:
            await master_onboarding.review_onboarding(
                session,
                current_user=platform,
                master_id=seeded["pending_master"],
                decision="APPROVE",
            )

    async with maker() as session:
        with pytest.raises(MasterOnboardingNotFoundError) as missing:
            await master_onboarding.review_onboarding(
                session,
                current_user=platform,
                master_id=999999,
                decision="APPROVE",
            )

    assert str(twice.value) == str(missing.value)


@pytest.mark.integration
async def test_review_reject_twice_is_404(maker, db) -> None:
    """驳回后再驳回 -> 404（行已经没了）。"""
    seeded = await _seed(maker)
    platform = _current(seeded["platform_admin"], UserRole.PLATFORM_ADMIN)

    async with maker() as session:
        await master_onboarding.review_onboarding(
            session,
            current_user=platform,
            master_id=seeded["pending_master"],
            decision="REJECT",
        )

    async with maker() as session:
        with pytest.raises(MasterOnboardingNotFoundError):
            await master_onboarding.review_onboarding(
                session,
                current_user=platform,
                master_id=seeded["pending_master"],
                decision="REJECT",
            )


@pytest.mark.integration
async def test_review_reject_cannot_delete_an_active_master(maker, db) -> None:
    """已入职（ACTIVE）的师傅不能被「驳回」删掉。

    驳回只对「待审核」（PENDING）的申请有效——否则一个手滑的驳回
    就能把一个已经入职的师傅从库里抹掉（连带他的历史订单失去归属）。
    """
    seeded = await _seed(maker)
    platform = _current(seeded["platform_admin"], UserRole.PLATFORM_ADMIN)

    async with maker() as session:
        with pytest.raises(MasterOnboardingNotFoundError):
            await master_onboarding.review_onboarding(
                session,
                current_user=platform,
                master_id=seeded["active_master"],
                decision="REJECT",
            )

    async with maker() as session:
        master = (
            await session.execute(
                select(Master).where(Master.id == seeded["active_master"])
            )
        ).scalar_one()
    assert master.status is MasterStatus.ACTIVE


@pytest.mark.integration
async def test_review_reject_refuses_master_with_orders(maker, db) -> None:
    """有订单的师傅不能被删（删了订单就失去归属）。

    正常流程下不可能出现（被驳回的是还没入职的师傅），
    出现就说明服务端数据坏了 —— 报 500，不悄悄删掉。
    """
    seeded = await _seed(maker)
    platform = _current(seeded["platform_admin"], UserRole.PLATFORM_ADMIN)
    await _seed_order_for(maker, master_id=seeded["pending_master"])

    async with maker() as session:
        with pytest.raises(MasterOnboardingInvariantError):
            await master_onboarding.review_onboarding(
                session,
                current_user=platform,
                master_id=seeded["pending_master"],
                decision="REJECT",
            )

    async with maker() as session:
        master = (
            await session.execute(
                select(Master).where(Master.id == seeded["pending_master"])
            )
        ).scalar_one()
    assert master is not None


# =====================================================================
# 并发
# =====================================================================


@pytest.mark.integration
async def test_concurrent_submit_only_one_succeeds(maker, db, monkeypatch) -> None:
    """两个请求同时登记同一份申请 -> 只有一个成功，另一个 409。

    会合点落在「实现第一次碰到 master 表的位置」（查已有师傅身份那一步）：
    两个请求都在这里等对方到齐，然后同时往下走 insert，
    后到的那个撞 ``uq_master_user_id``。
    """
    seeded = await _seed(maker)
    current = _current(seeded["plain_user"])
    rendezvous = Rendezvous(parties=2)

    original = master_onboarding._find_existing_master

    async def _with_barrier(session, user_id):
        row = await original(session, user_id)
        await rendezvous.wait()
        return row

    monkeypatch.setattr(master_onboarding, "_find_existing_master", _with_barrier)

    async def _submit():
        async with maker() as session:
            try:
                await master_onboarding.submit_onboarding(
                    session,
                    current_user=current,
                    real_name="张师傅",
                    target_provider_id=seeded["provider_active"],
                )
                return "ok"
            except MasterOnboardingConflictError:
                return "conflict"

    results = await asyncio.gather(_submit(), _submit())
    assert sorted(results) == ["conflict", "ok"]

    async with maker() as session:
        count = (
            await session.execute(
                select(func.count()).select_from(Master).where(
                    Master.user_id == seeded["plain_user"]
                )
            )
        ).scalar_one()
    assert count == 1


@pytest.mark.integration
async def test_concurrent_approve_and_reject_leaves_master_intact(
    maker, db, monkeypatch
) -> None:
    """一个管理员点「通过」、另一个点「驳回」-> 只能有一个生效。

    而且**师傅不能被删掉**：驳回那条的 DELETE 带着
    ``AND status='PENDING'`` 谓词，等锁期间「通过」已经把状态改成 ACTIVE，
    谓词重求值不成立 -> 改 0 行 -> 404。
    （没有这个谓词的话，驳回会把刚通过审核的师傅从库里抹掉。）
    """
    seeded = await _seed(maker)
    platform = _current(seeded["platform_admin"], UserRole.PLATFORM_ADMIN)
    rendezvous = Rendezvous(parties=2)

    original = master_onboarding._load_application

    async def _with_barrier(session, master_id):
        row = await original(session, master_id)
        await rendezvous.wait()
        return row

    monkeypatch.setattr(master_onboarding, "_load_application", _with_barrier)

    async def _review(decision):
        async with maker() as session:
            try:
                await master_onboarding.review_onboarding(
                    session,
                    current_user=platform,
                    master_id=seeded["pending_master"],
                    decision=decision,
                )
                return decision
            except MasterOnboardingNotFoundError:
                return "not_found"

    results = await asyncio.gather(_review("APPROVE"), _review("REJECT"))
    assert sorted(results) == ["APPROVE", "not_found"]

    async with maker() as session:
        master = (
            await session.execute(
                select(Master).where(Master.id == seeded["pending_master"])
            )
        ).scalar_one()
    # 师傅还在，且是「已入职」——没有被驳回那条删掉
    assert master.status is MasterStatus.ACTIVE


@pytest.mark.integration
async def test_concurrent_review_only_one_succeeds(maker, db, monkeypatch) -> None:
    """两个平台管理员同时审同一份申请 -> 只有一个成功，另一个 404。

    会合点落在「读出要审核的那份申请」这一步：两个请求都读到 PENDING，
    然后各自去 UPDATE，条件 UPDATE（``AND status='PENDING'``）
    让其中一个改 0 行。
    """
    seeded = await _seed(maker)
    platform = _current(seeded["platform_admin"], UserRole.PLATFORM_ADMIN)
    rendezvous = Rendezvous(parties=2)

    original = master_onboarding._load_application

    async def _with_barrier(session, master_id):
        row = await original(session, master_id)
        await rendezvous.wait()
        return row

    monkeypatch.setattr(master_onboarding, "_load_application", _with_barrier)

    async def _review():
        async with maker() as session:
            try:
                await master_onboarding.review_onboarding(
                    session,
                    current_user=platform,
                    master_id=seeded["pending_master"],
                    decision="APPROVE",
                )
                return "ok"
            except MasterOnboardingNotFoundError:
                return "not_found"

    results = await asyncio.gather(_review(), _review())
    assert sorted(results) == ["not_found", "ok"]

    async with maker() as session:
        master = (
            await session.execute(
                select(Master).where(Master.id == seeded["pending_master"])
            )
        ).scalar_one()
        logs = (
            await session.execute(
                select(AuditLog).where(
                    AuditLog.target_type == "master",
                    AuditLog.target_id == seeded["pending_master"],
                )
            )
        ).scalars().all()

    assert master.status is MasterStatus.ACTIVE
    # 留痕只有一条：两个管理员都「审核成功」是不允许的
    assert len(logs) == 1


# =====================================================================
# 一致性（T-09a-0 记下来的技术债，本卡补校验）
# =====================================================================


@pytest.mark.integration
async def test_identity_is_consistent_after_full_flow(maker, db) -> None:
    """走完一整条流程后，master 表与 user 表必须一一对应。

    规则：

    - 每个 master 行对应一个账号，账号角色是 MASTER、provider_id 为空；
    - 每个 MASTER 角色的账号恰好有一个 master 行。
    """
    seeded = await _seed(maker)
    platform = _current(seeded["platform_admin"], UserRole.PLATFORM_ADMIN)

    async with maker() as session:
        submission = await master_onboarding.submit_onboarding(
            session,
            current_user=_current(seeded["plain_user"]),
            real_name="张师傅",
            target_provider_id=seeded["provider_active"],
        )

    async with maker() as session:
        # 新登记的那份 -> 通过
        await master_onboarding.review_onboarding(
            session,
            current_user=platform,
            master_id=submission.master_id,
            decision="APPROVE",
        )
        # 原本审核中的那份 -> 驳回（删行、角色回退）
        await master_onboarding.review_onboarding(
            session,
            current_user=platform,
            master_id=seeded["pending_master"],
            decision="REJECT",
        )

    async with maker() as session:
        rows = (
            await session.execute(
                select(Master.id, Master.user_id, User.role, User.provider_id)
                .join(User, User.id == Master.user_id)
            )
        ).all()
        master_users = set(
            (
                await session.execute(
                    select(User.id).where(User.role == UserRole.MASTER)
                )
            ).scalars().all()
        )
        master_ids = {row[0] for row in rows}
        user_ids = {row[1] for row in rows}

    for master_id, user_id, role, provider_id in rows:
        assert role is UserRole.MASTER, master_id
        assert provider_id is None, master_id

    # 每个 MASTER 账号都恰好有一个 master 行
    assert master_users == user_ids


# =====================================================================
# 一致性校验本身（防御性断言）
# =====================================================================


@pytest.mark.integration
async def test_assert_identity_consistent_detects_role_mismatch(maker, db) -> None:
    """师傅的登录账号角色不是 MASTER -> 报内部一致性错误（500）。

    这条数据在正常流程下不会出现（角色是登记时改的）。
    校验它的意义是：**万一**出现了，不能装作没这回事。
    """
    seeded = await _seed(maker)

    async with maker() as session:
        with pytest.raises(MasterOnboardingInvariantError):
            await master_onboarding._assert_identity_consistent(
                session,
                user_id=seeded["plain_user"],
                master_id=seeded["pending_master"],
            )


@pytest.mark.integration
async def test_assert_identity_consistent_detects_missing_master(maker, db) -> None:
    """这一行师傅不属于这个账号 -> 报内部一致性错误。"""
    seeded = await _seed(maker)

    async with maker() as session:
        with pytest.raises(MasterOnboardingInvariantError):
            await master_onboarding._assert_identity_consistent(
                session,
                user_id=seeded["pending_master_user"],
                master_id=seeded["active_master"],
            )


# =====================================================================
# 列表
# =====================================================================


@pytest.mark.integration
async def test_list_joinable_providers_only_active(maker, db) -> None:
    """可加入的服务商只有 ACTIVE 的那些。"""
    seeded = await _seed(maker)

    async with maker() as session:
        providers = await master_onboarding.list_joinable_providers(session)

    assert [provider.id for provider in providers] == [
        seeded["provider_active"],
        seeded["provider_active_b"],
    ]


@pytest.mark.integration
async def test_list_applications_filters_and_paginates(maker, db) -> None:
    """平台侧列表：能按状态过滤，分页参数收敛。"""
    seeded = await _seed(maker)

    async with maker() as session:
        pending, pending_total = await master_onboarding.list_onboarding_applications(
            session, status=MasterStatus.PENDING
        )
        everything, total = await master_onboarding.list_onboarding_applications(
            session
        )
        first_page, _ = await master_onboarding.list_onboarding_applications(
            session, page=1, limit=1
        )

    assert [row.id for row in pending] == [seeded["pending_master"]]
    assert pending_total == 1
    assert total == 3
    assert len(first_page) == 1
    # 列表里能看到申请人的手机号（平台要联系本人核实资质）
    assert pending[0].phone == "13800000005"
    assert pending[0].provider_name == "甲服务商"
