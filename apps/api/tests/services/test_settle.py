"""T+1 待结算生成 service / 任务脚本的测试。

分两类：

- **单元测试**（不碰数据库）：金额拆分口径、脚本入口、
  service 的签名与时间归一；
- **集成测试**（需要真实 PostgreSQL）：真的走 service -> 数据库，
  验证同一服务商聚成一张结算单、未满 T+1 不结算、不同服务商分开、
  幂等、并发跑只生成一次、结算单留审计日志、以及一个服务商失败不拖垮整批。

集成测试用的数据库是 TEST_DATABASE_URL 指向的独立测试库
（集成 fixture 每次 drop_all + create_all，绝不碰开发库）。
"""
from __future__ import annotations

import asyncio
import inspect
import logging
import os
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from tests.support import business_today
from app.core.timezone import business_date, business_datetime
from app.models.address import Address
from app.models.audit_log import AuditLog
from app.models.base import Base
from app.models.catalog import ServiceCategory, ServiceItem
from app.models.enums import (
    MasterStatus,
    OperatorType,
    OrderStatus,
    PayStatus,
    SettlementStatus,
    UserRole,
)
from app.models.order import Order, OrderStatusLog
from app.models.provider import Master, ServiceProvider
from app.models.schedule_slot import ScheduleSlot
from app.models.settlement import Settlement, SettlementItem
from app.models.user import User
from app.scripts import settle_job
from app.services import settle as settle_service
from app.services.settle import (
    AUDIT_REASON,
    SETTLE_DELAY_DAYS,
    SETTLE_REASON,
    _resolve_now,
    _split_amounts,
    generate_pending_settlements,
)

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

# ---------------------------------------------------------------------
# 种子数据里的 id
# ---------------------------------------------------------------------

PROVIDER_A_ID = 1  # 佣金率 20%
PROVIDER_B_ID = 2  # 佣金率 10%

CUSTOMER_USER_ID = 1
MASTER_A_USER_ID = 2
MASTER_B_USER_ID = 3

MASTER_A_ID = 1
MASTER_B_ID = 2

# 完工满 T+1，应进结算
ORDER_A1_ID = 1  # 服务商 A，100.00，3 天前完工
ORDER_A2_ID = 2  # 服务商 A，50.00，2 天前完工
ORDER_B1_ID = 4  # 服务商 B，200.00，2 天前完工
# 服务商 A，60.00，UTC 16:00 完工（= 北京时间次日 00:00），边界用例专用
ORDER_C1_ID = 5
# 刚完工，没满 T+1，不该进结算
ORDER_A3_ID = 3  # 服务商 A，80.00，1 小时前完工

ORDER_A1_NO = "OTO20260401000001"
ORDER_A2_NO = "OTO20260401000002"
ORDER_A3_NO = "OTO20260401000003"
ORDER_B1_NO = "OTO20260401000004"
ORDER_C1_NO = "OTO20260401000005"

PROVIDER_A_RATE = Decimal("0.2000")
PROVIDER_B_RATE = Decimal("0.1000")


# =====================================================================
# 单元测试：金额口径、签名、脚本入口
# =====================================================================


def test_split_amounts_uses_provider_commission_rate() -> None:
    """佣金 = 合计 × 费率；实收 = 合计 - 佣金。"""
    commission, net = _split_amounts(Decimal("150.00"), Decimal("0.2000"))
    assert commission == Decimal("30.00")
    assert net == Decimal("120.00")


def test_split_amounts_rounds_to_cents() -> None:
    """金额四舍五入到分，不会出现 3 位小数。"""
    commission, net = _split_amounts(Decimal("10.00"), Decimal("0.3333"))
    assert commission == Decimal("3.33")
    assert net == Decimal("6.67")
    assert -commission.as_tuple().exponent <= 2


def test_split_amounts_handles_zero_rate() -> None:
    """佣金率 0 -> 佣金 0、实收等于合计（不能把整笔钱当佣金扣掉）。"""
    commission, net = _split_amounts(Decimal("99.99"), Decimal("0"))
    assert commission == Decimal("0.00")
    assert net == Decimal("99.99")


def test_settle_delay_is_one_day() -> None:
    """T+1：完工满一天才进结算。"""
    assert SETTLE_DELAY_DAYS == 1


def test_generate_signature_takes_no_order_id() -> None:
    """generate_pending_settlements 的签名里没有 order_id。

    它处理的是「所有该结算的订单」，订单从库里查，不该由调用方指定。
    """
    parameters = inspect.signature(generate_pending_settlements).parameters
    assert "order_id" not in parameters
    assert "order_no" not in parameters
    assert "now" in parameters


def test_resolve_now_treats_naive_datetime_as_utc() -> None:
    """naive 时间按 UTC 解释（库里是 timestamptz，naive 比较会抛异常）。"""
    naive = datetime(2026, 4, 1, 12, 0, 0)
    assert _resolve_now(naive) == naive.replace(tzinfo=timezone.utc)
    assert _resolve_now(naive).tzinfo is not None


def test_script_has_executable_entrypoint() -> None:
    """脚本是独立可执行入口。"""
    assert callable(settle_job.main)
    assert callable(settle_job.run_once)


async def test_script_calls_service(monkeypatch) -> None:
    """脚本调 service 跑一轮，把笔数透传出来。"""
    calls = []

    async def _fake_generate(session, *, now=None):
        calls.append(now)
        return 4

    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

    monkeypatch.setattr(
        settle_job, "generate_pending_settlements", _fake_generate
    )
    monkeypatch.setattr(settle_job, "session_factory", lambda: _FakeSession())

    count = await settle_job.run_once()

    assert count == 4
    assert calls == [None]


# =====================================================================
# 集成测试：需要真实 PostgreSQL
# =====================================================================


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
async def seeded(db):
    """种两个服务商、三个账号、两个师傅、四笔「已完成」订单。

    三笔完工满一天（应结算），一笔刚完工（不满 T+1，不结算）。
    """
    maker = async_sessionmaker(db, class_=AsyncSession, expire_on_commit=False)
    tomorrow = business_today() + timedelta(days=1)
    now = datetime.now(timezone.utc)
    # 完工时刻按**业务日期**摆，不按「现在往前推几小时」：
    # 「1 小时前完工」这种相对时间会在北京时间凌晨跨到前一个业务日，
    # 用例就会随机红。业务零点往前推 N 天 = N 个业务日之前，确定。
    business_midnight = business_datetime(business_today(), time.min)
    async with maker() as session:
        session.add_all(
            [
                ServiceProvider(
                    id=PROVIDER_A_ID,
                    name="服务商甲",
                    contact_phone="13800000001",
                    commission_rate=PROVIDER_A_RATE,
                ),
                ServiceProvider(
                    id=PROVIDER_B_ID,
                    name="服务商乙",
                    contact_phone="13800000002",
                    commission_rate=PROVIDER_B_RATE,
                ),
            ]
        )
        await session.flush()

        session.add_all(
            [
                User(id=CUSTOMER_USER_ID, phone="13900000001", role=UserRole.USER),
                User(id=MASTER_A_USER_ID, phone="13900000002", role=UserRole.MASTER),
                User(id=MASTER_B_USER_ID, phone="13900000003", role=UserRole.MASTER),
            ]
        )
        await session.flush()

        session.add(ServiceCategory(id=1, name="测试分类"))
        await session.flush()
        session.add(
            ServiceItem(
                id=2,
                category_id=1,
                name="测试服务项",
                base_price=Decimal("100.00"),
                duration_min=60,
            )
        )
        await session.flush()

        session.add(
            Address(
                id=3,
                user_id=CUSTOMER_USER_ID,
                contact="张三",
                phone="13900000001",
                region="北京",
                detail="某街道 1 号",
            )
        )
        await session.flush()

        session.add(
            ScheduleSlot(
                id=4,
                item_id=2,
                date=tomorrow,
                start_time=time(9, 0),
                end_time=time(12, 0),
                capacity=5,
            )
        )
        await session.flush()

        session.add_all(
            [
                Master(
                    id=MASTER_A_ID,
                    provider_id=PROVIDER_A_ID,
                    user_id=MASTER_A_USER_ID,
                    real_name="张师傅",
                    status=MasterStatus.ACTIVE,
                ),
                Master(
                    id=MASTER_B_ID,
                    provider_id=PROVIDER_B_ID,
                    user_id=MASTER_B_USER_ID,
                    real_name="李师傅",
                    status=MasterStatus.ACTIVE,
                ),
            ]
        )
        await session.flush()

        def _order(
            order_id: int,
            order_no: str,
            provider_id: int,
            master_id: int,
            amount: Decimal,
            completed_at: datetime,
        ) -> Order:
            return Order(
                id=order_id,
                order_no=order_no,
                user_id=CUSTOMER_USER_ID,
                provider_id=provider_id,
                master_id=master_id,
                address_id=3,
                item_id=2,
                slot_id=4,
                amount=amount,
                status=OrderStatus.COMPLETED,
                pay_status=PayStatus.PAID,
                paid_at=completed_at,
                dispatched_at=completed_at,
                accepted_at=completed_at,
                completed_at=completed_at,
                updated_at=completed_at,
            )

        session.add_all(
            [
                _order(
                    ORDER_A1_ID,
                    ORDER_A1_NO,
                    PROVIDER_A_ID,
                    MASTER_A_ID,
                    Decimal("100.00"),
                    business_midnight - timedelta(days=3),
                ),
                _order(
                    ORDER_A2_ID,
                    ORDER_A2_NO,
                    PROVIDER_A_ID,
                    MASTER_A_ID,
                    Decimal("50.00"),
                    business_midnight - timedelta(days=2),
                ),
                _order(
                    ORDER_A3_ID,
                    ORDER_A3_NO,
                    PROVIDER_A_ID,
                    MASTER_A_ID,
                    Decimal("80.00"),
                    # 今天业务日的零点：还在今天，没满 T+1
                    business_midnight,
                ),
                _order(
                    ORDER_B1_ID,
                    ORDER_B1_NO,
                    PROVIDER_B_ID,
                    MASTER_B_ID,
                    Decimal("200.00"),
                    business_midnight - timedelta(days=2),
                ),
            ]
        )
        await session.flush()
        await session.commit()
    return True


def _maker(db) -> async_sessionmaker:
    return async_sessionmaker(db, class_=AsyncSession, expire_on_commit=False)


async def _run(db, *, now: datetime | None = None) -> int:
    maker = _maker(db)
    async with maker() as session:
        return await generate_pending_settlements(session, now=now)


async def _settlements_of(db, *, provider_id: int | None = None) -> list[Settlement]:
    maker = _maker(db)
    async with maker() as session:
        query = select(Settlement).order_by(Settlement.id)
        if provider_id is not None:
            query = query.where(Settlement.provider_id == provider_id)
        return list((await session.execute(query)).scalars().all())


async def _items_of(db, *, settlement_id: int | None = None) -> list[SettlementItem]:
    maker = _maker(db)
    async with maker() as session:
        query = select(SettlementItem).order_by(SettlementItem.id)
        if settlement_id is not None:
            query = query.where(SettlementItem.settlement_id == settlement_id)
        return list((await session.execute(query)).scalars().all())


async def _order_of(db, order_id: int) -> Order:
    maker = _maker(db)
    async with maker() as session:
        return (
            await session.execute(select(Order).where(Order.id == order_id))
        ).scalar_one()


async def _logs_of(db, order_id: int) -> list[OrderStatusLog]:
    maker = _maker(db)
    async with maker() as session:
        rows = (
            await session.execute(
                select(OrderStatusLog).where(OrderStatusLog.order_id == order_id)
            )
        ).scalars().all()
        return list(rows)


async def _audit_logs_of(
    db, *, target_id: int | None = None
) -> list[AuditLog]:
    maker = _maker(db)
    async with maker() as session:
        query = select(AuditLog).order_by(AuditLog.id)
        if target_id is not None:
            query = query.where(AuditLog.target_id == target_id)
        return list((await session.execute(query)).scalars().all())


# ---------------------------------------------------------------------
# 1. 同一服务商的多笔订单聚成一张结算单
# ---------------------------------------------------------------------


@pytest.mark.integration
async def test_same_provider_orders_become_one_settlement(db, seeded) -> None:
    """两笔同服务商的完成订单 -> 一张结算单，金额算对。"""
    count = await _run(db)

    # 一共三笔该结算的订单（服务商甲 2 笔 + 乙 1 笔）
    assert count == 3

    settlements = await _settlements_of(db, provider_id=PROVIDER_A_ID)
    assert len(settlements) == 1

    settlement = settlements[0]
    assert settlement.status == SettlementStatus.PENDING
    # 合计 100 + 50 = 150
    assert settlement.total_amount == Decimal("150.00")
    # 佣金 20% = 30
    assert settlement.commission_amount == Decimal("30.00")
    # 实收 = 150 - 30 = 120
    assert settlement.net_amount == Decimal("120.00")
    # 周期覆盖两笔订单的完工日期
    order_a1 = await _order_of(db, ORDER_A1_ID)
    order_a2 = await _order_of(db, ORDER_A2_ID)
    # 周期按**业务日期**算（不是 UTC 日期）
    assert settlement.period_start == business_date(order_a1.completed_at)
    assert settlement.period_end == business_date(order_a2.completed_at)

    items = await _items_of(db, settlement_id=settlement.id)
    assert sorted(item.order_id for item in items) == [ORDER_A1_ID, ORDER_A2_ID]

    # 订单状态确实转了，并留痕
    for order in (order_a1, order_a2):
        order_id = order.id
        assert order.status == OrderStatus.PENDING_SETTLE

        logs = await _logs_of(db, order_id)
        assert len(logs) == 1
        assert logs[0].from_status == OrderStatus.COMPLETED
        assert logs[0].to_status == OrderStatus.PENDING_SETTLE
        assert logs[0].operator_type == OperatorType.SYSTEM
        assert logs[0].operator_id == 0
        assert logs[0].reason == SETTLE_REASON


# ---------------------------------------------------------------------
# 2. 未满 T+1 不结算
# ---------------------------------------------------------------------


@pytest.mark.integration
async def test_order_before_t_plus_one_is_not_settled(db, seeded) -> None:
    """刚完工的订单不进结算单，状态也不变。"""
    count = await _run(db)

    # 只有三笔满 T+1 的订单被结算，刚完工的那笔不在其中
    assert count == 3

    fresh = await _order_of(db, ORDER_A3_ID)
    assert fresh.status == OrderStatus.COMPLETED

    items = await _items_of(db)
    assert ORDER_A3_ID not in [item.order_id for item in items]
    assert len(items) == 3


# ---------------------------------------------------------------------
# 3. 不同服务商分到不同结算单
# ---------------------------------------------------------------------


@pytest.mark.integration
async def test_different_providers_get_different_settlements(db, seeded) -> None:
    """服务商甲、乙各一张结算单，佣金率各按各的算。"""
    count = await _run(db)

    assert count == 3

    all_settlements = await _settlements_of(db)
    assert len(all_settlements) == 2
    assert sorted(s.provider_id for s in all_settlements) == [
        PROVIDER_A_ID,
        PROVIDER_B_ID,
    ]

    b_settlements = await _settlements_of(db, provider_id=PROVIDER_B_ID)
    assert len(b_settlements) == 1
    b_settlement = b_settlements[0]
    assert b_settlement.total_amount == Decimal("200.00")
    # 乙的佣金率 10% = 20
    assert b_settlement.commission_amount == Decimal("20.00")
    assert b_settlement.net_amount == Decimal("180.00")


# ---------------------------------------------------------------------
# 4. 幂等
# ---------------------------------------------------------------------


@pytest.mark.integration
async def test_generate_is_idempotent(db, seeded) -> None:
    """连跑两次：第二次转 0 笔，也不会多出结算单或明细。

    这是 cron 每天跑一次的前提——重复执行不能把同一笔订单结算两遍。
    """
    first = await _run(db)
    assert first == 3

    second = await _run(db)
    assert second == 0

    settlements = await _settlements_of(db)
    assert len(settlements) == 2

    a_items = await _items_of(db)
    assert len(a_items) == 3
    # 每笔订单只出现一次
    order_ids = [item.order_id for item in a_items]
    assert sorted(order_ids) == [ORDER_A1_ID, ORDER_A2_ID, ORDER_B1_ID]
    assert len(set(order_ids)) == len(order_ids)


# ---------------------------------------------------------------------
# 5. 并发跑两次只生成一次
# ---------------------------------------------------------------------


@pytest.mark.integration
async def test_concurrent_runs_generate_settlement_once(db, seeded, caplog) -> None:
    """两个任务实例同时跑：同一服务商仍然只有一张结算单。

    用第三个会话先锁住一笔订单，逼两个实例真的撞上同一行
    （否则它们可能一个跑完了另一个才开始，根本没并发）。

    认领订单用的是条件 UPDATE（WHERE id=? AND status='COMPLETED'），
    行锁 + 谓词重求值裁决并发：先拿到锁的一方赢，另一方等锁期间
    谓词已不成立（订单已是「待结算」），认领不到。

    顺带盯住「没有异常日志」：如果靠数据库唯一约束兜底才没重复结算，
    日志里会留下 IntegrityError——那说明条件 UPDATE 没起作用。
    """
    maker = _maker(db)
    locker = maker()
    await locker.begin()
    await locker.execute(
        select(Order).where(Order.id == ORDER_A1_ID).with_for_update()
    )

    with caplog.at_level("ERROR", logger="app.services.settle"):
        task = asyncio.gather(_run(db), _run(db))
        # 让两个实例都堵在行锁上
        await asyncio.sleep(0.5)
        # 放行：两个实例同时去认领同一笔订单
        await locker.commit()
        results = await task
    await locker.close()

    # 两边加起来正好把所有该结算的订单结算一遍，不多不少
    assert sum(results) == 3

    # 每个服务商各一张结算单，没有多出来
    all_settlements = await _settlements_of(db)
    assert len(all_settlements) == 2
    assert sorted(s.provider_id for s in all_settlements) == [
        PROVIDER_A_ID,
        PROVIDER_B_ID,
    ]

    a_settlements = await _settlements_of(db, provider_id=PROVIDER_A_ID)
    assert len(a_settlements) == 1
    assert a_settlements[0].total_amount == Decimal("150.00")

    # 每笔订单只被结算一次
    items = await _items_of(db)
    order_ids = sorted(item.order_id for item in items)
    assert order_ids == [ORDER_A1_ID, ORDER_A2_ID, ORDER_B1_ID]
    assert len(set(order_ids)) == len(order_ids)

    # 竞争是被条件 UPDATE 裁决掉的，不是靠唯一约束报错兜底的
    errors = [record for record in caplog.records if record.levelno >= logging.ERROR]
    assert errors == [], "并发结算不应该产生异常日志：{}".format(
        [record.getMessage() for record in errors]
    )


# ---------------------------------------------------------------------
# 6. 生成结算单要留审计日志
# ---------------------------------------------------------------------


@pytest.mark.integration
async def test_settlement_writes_audit_log(db, seeded) -> None:
    """结算单一落库，金额三件套就各留下一条审计日志。

    审计日志和结算单在同一个事务里——没审计日志的结算单等于没记录。
    """
    count = await _run(db)
    assert count == 3

    settlements = await _settlements_of(db)
    assert len(settlements) == 2

    for settlement in settlements:
        logs = await _audit_logs_of(db, target_id=settlement.id)

        # 金额三个字段各一条，不多不少
        assert len(logs) == 3
        assert sorted(log.field_name for log in logs) == [
            "commission_amount",
            "net_amount",
            "total_amount",
        ]

        by_field = {log.field_name: log for log in logs}
        for log in logs:
            assert log.target_type == "settlement"
            assert log.target_id == settlement.id
            assert log.provider_id == settlement.provider_id
            assert log.operator_type == OperatorType.SYSTEM
            assert log.operator_id == 0
            assert log.reason == AUDIT_REASON
            # 结算单是新建的，之前没有值
            assert log.old_value is None

        assert by_field["total_amount"].new_value == str(settlement.total_amount)
        assert (
            by_field["commission_amount"].new_value
            == str(settlement.commission_amount)
        )
        assert by_field["net_amount"].new_value == str(settlement.net_amount)

    # 两张结算单 -> 六条审计日志
    assert len(await _audit_logs_of(db)) == 6


# ---------------------------------------------------------------------
# 7. 一个服务商出错，不影响其他服务商
# ---------------------------------------------------------------------


@pytest.mark.integration
async def test_provider_failure_does_not_stop_others(
    db, seeded, monkeypatch, caplog
) -> None:
    """服务商甲那一组炸了，乙照常结算，整体也不抛异常。

    定时任务因为一个服务商的脏数据整批失败，比漏掉一个服务商更糟——
    所以单组失败只记日志、继续下一组。
    """
    real_settle = settle_service._settle_provider

    async def flaky_settle(session, *, provider_id, rows, now):
        if provider_id == PROVIDER_A_ID:
            raise RuntimeError("模拟服务商甲的脏数据")
        return await real_settle(
            session, provider_id=provider_id, rows=rows, now=now
        )

    monkeypatch.setattr(settle_service, "_settle_provider", flaky_settle)

    with caplog.at_level("ERROR", logger="app.services.settle"):
        # 不抛异常
        count = await _run(db)

    # (a) 乙照常结算，金额正确
    assert count == 1

    b_settlements = await _settlements_of(db, provider_id=PROVIDER_B_ID)
    assert len(b_settlements) == 1
    b_settlement = b_settlements[0]
    assert b_settlement.total_amount == Decimal("200.00")
    assert b_settlement.commission_amount == Decimal("20.00")
    assert b_settlement.net_amount == Decimal("180.00")

    b_order = await _order_of(db, ORDER_B1_ID)
    assert b_order.status == OrderStatus.PENDING_SETTLE

    b_items = await _items_of(db, settlement_id=b_settlement.id)
    assert [item.order_id for item in b_items] == [ORDER_B1_ID]

    # (b) 甲：订单仍是「已完成」，没有结算单、没有明细、没有状态流转日志
    assert await _settlements_of(db, provider_id=PROVIDER_A_ID) == []

    all_items = await _items_of(db)
    assert [item.order_id for item in all_items] == [ORDER_B1_ID]

    for order_id in (ORDER_A1_ID, ORDER_A2_ID):
        order = await _order_of(db, order_id)
        assert order.status == OrderStatus.COMPLETED
        assert await _logs_of(db, order_id) == []

    # 失败的这一组确实被记了日志（不是悄悄吞掉）
    errors = [record for record in caplog.records if record.levelno >= logging.ERROR]
    assert any("provider_id={}".format(PROVIDER_A_ID) in record.getMessage() for record in errors)



# ---------------------------------------------------------------------
# 8. T+1 的边界是「业务零点」
# ---------------------------------------------------------------------


@pytest.mark.integration
async def test_t_plus_one_boundary_is_business_midnight(db, seeded) -> None:
    """UTC 16:00 完工的单，次日（+8 小时）才进 PENDING_SETTLE。

    完工时刻 2026-11-14T16:00Z = 北京时间 2026-11-15 00:00（业务日期 11-15）。
    T+1 的意思是：业务日期 11-16 那天（= 2026-11-15T16:00Z 之后）才进结算。

    边界之前（北京时间 11-15 23:59:59）：还是「已完成」；
    边界之上（北京时间 11-16 00:00）：转「待结算」。
    """
    completed_at = datetime(2026, 11, 14, 16, 0, tzinfo=timezone.utc)
    maker = _maker(db)
    async with maker() as session:
        session.add(
            Order(
                id=ORDER_C1_ID,
                order_no=ORDER_C1_NO,
                user_id=CUSTOMER_USER_ID,
                provider_id=PROVIDER_A_ID,
                master_id=MASTER_A_ID,
                address_id=3,
                item_id=2,
                slot_id=4,
                amount=Decimal("60.00"),
                status=OrderStatus.COMPLETED,
                pay_status=PayStatus.PAID,
                paid_at=completed_at,
                dispatched_at=completed_at,
                accepted_at=completed_at,
                completed_at=completed_at,
                updated_at=completed_at,
            )
        )
        await session.commit()

    # 边界之前：北京时间 2026-11-15 23:59:59
    await _run(db, now=datetime(2026, 11, 15, 15, 59, 59, tzinfo=timezone.utc))
    order = await _order_of(db, ORDER_C1_ID)
    assert order.status == OrderStatus.COMPLETED

    # 边界之上：北京时间 2026-11-16 00:00（= 2026-11-15T16:00Z）
    await _run(db, now=datetime(2026, 11, 15, 16, 0, tzinfo=timezone.utc))
    order = await _order_of(db, ORDER_C1_ID)
    assert order.status == OrderStatus.PENDING_SETTLE

    # 结算周期按业务日期算：这一单的业务日期是 2026-11-15
    # （周期终点取的是这一批里最晚的业务日期，与 UTC 日期无关）
    items = await _items_of(db)
    c1_items = [item for item in items if item.order_id == ORDER_C1_ID]
    assert len(c1_items) == 1
    c1_settlement = next(
        s
        for s in await _settlements_of(db)
        if s.id == c1_items[0].settlement_id
    )
    assert c1_settlement.period_end == date(2026, 11, 15)
