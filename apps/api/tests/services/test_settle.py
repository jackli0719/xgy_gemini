"""T+1 待结算生成 service / 任务脚本的测试。

分两类：

- **单元测试**（不碰数据库）：金额拆分口径、脚本入口、
  service 的签名与时间归一；
- **集成测试**（需要真实 PostgreSQL）：真的走 service -> 数据库，
  验证同一服务商聚成一张结算单、未满 T+1 不结算、不同服务商分开、
  幂等、以及并发跑只生成一次。

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

from app.models.address import Address
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
from app.services.settle import (
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
# 刚完工，没满 T+1，不该进结算
ORDER_A3_ID = 3  # 服务商 A，80.00，1 小时前完工

ORDER_A1_NO = "OTO20260401000001"
ORDER_A2_NO = "OTO20260401000002"
ORDER_A3_NO = "OTO20260401000003"
ORDER_B1_NO = "OTO20260401000004"

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
    tomorrow = date.today() + timedelta(days=1)
    now = datetime.now(timezone.utc)
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
                    now - timedelta(days=3),
                ),
                _order(
                    ORDER_A2_ID,
                    ORDER_A2_NO,
                    PROVIDER_A_ID,
                    MASTER_A_ID,
                    Decimal("50.00"),
                    now - timedelta(days=2),
                ),
                _order(
                    ORDER_A3_ID,
                    ORDER_A3_NO,
                    PROVIDER_A_ID,
                    MASTER_A_ID,
                    Decimal("80.00"),
                    now - timedelta(hours=1),
                ),
                _order(
                    ORDER_B1_ID,
                    ORDER_B1_NO,
                    PROVIDER_B_ID,
                    MASTER_B_ID,
                    Decimal("200.00"),
                    now - timedelta(days=2),
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
    assert settlement.period_start == order_a1.completed_at.date()
    assert settlement.period_end == order_a2.completed_at.date()

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
