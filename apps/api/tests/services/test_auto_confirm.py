"""超时自动确认 service / 任务脚本的测试。

分两类：

- **单元测试**（不碰数据库）：阈值来自配置而不是硬编码、阈值为负直接报错、
  脚本入口确实按配置调 service；
- **集成测试**（需要真实 PostgreSQL）：真的走 service -> 数据库，
  验证只确认超时的订单、未超时的不动、幂等、以及单笔失败不拖垮整批。

集成测试用的数据库是 TEST_DATABASE_URL 指向的独立测试库
（集成 fixture 每次 drop_all + create_all，绝不碰开发库）。
"""
from __future__ import annotations

import inspect
import os
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.services.auto_confirm as auto_confirm_module
from app.core.config import settings
from app.models.address import Address
from app.models.base import Base
from app.models.catalog import ServiceCategory, ServiceItem
from app.models.enums import (
    MasterStatus,
    OperatorType,
    OrderStatus,
    PayStatus,
    UserRole,
)
from app.models.order import Order, OrderStatusLog
from app.models.provider import Master, ServiceProvider
from app.models.schedule_slot import ScheduleSlot
from app.models.user import User
from app.scripts import auto_confirm_job
from app.services.auto_confirm import (
    AUTO_CONFIRM_REASON,
    SYSTEM_OPERATOR_ID,
    _confirm_one,
    _resolve_threshold_hours,
    auto_confirm_expired,
)

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

# ---------------------------------------------------------------------
# 种子数据里的 id
# ---------------------------------------------------------------------

MY_PROVIDER_ID = 1
MY_MASTER_ID = 1

CUSTOMER_USER_ID = 1
MY_MASTER_USER_ID = 2

TIMED_OUT_ORDER_ID_1 = 1  # 超时 30 小时
TIMED_OUT_ORDER_ID_2 = 2  # 超时 48 小时
FRESH_ORDER_ID = 3  # 刚进「待确认」，没超时

BASE_PRICE = Decimal("100.00")

TIMED_OUT_ORDER_NO_1 = "OTO20260401000001"
TIMED_OUT_ORDER_NO_2 = "OTO20260401000002"
FRESH_ORDER_NO = "OTO20260401000003"


# =====================================================================
# 单元测试：阈值、脚本入口
# =====================================================================


def test_default_threshold_comes_from_config() -> None:
    """阈值来自配置，不是硬编码。

    配置项默认 24 小时；不传参时用它。
    """
    assert settings.auto_confirm_threshold_hours == 24
    assert _resolve_threshold_hours(None) == 24
    assert _resolve_threshold_hours(None) == settings.auto_confirm_threshold_hours


def test_threshold_can_be_overridden() -> None:
    """调用方可以显式传阈值覆盖配置。"""
    assert _resolve_threshold_hours(3) == 3


def test_non_positive_threshold_is_rejected() -> None:
    """阈值 <= 0 直接报错。

    阈值是 0 的话「所有待确认订单立刻被确认」，没完工的单子也会被确认掉。
    配置错了要炸，不要悄悄兜底。
    """
    for bad in (0, -1, -24):
        with pytest.raises(ValueError):
            _resolve_threshold_hours(bad)


def test_auto_confirm_signature_takes_no_order_id() -> None:
    """auto_confirm_expired 的签名里没有 order_id。

    它处理的是「所有超时的订单」，订单从库里查，不该由调用方指定。
    """
    parameters = inspect.signature(auto_confirm_expired).parameters
    assert "order_id" not in parameters
    assert "order_no" not in parameters
    assert "threshold_hours" in parameters


def test_script_has_executable_entrypoint() -> None:
    """脚本是独立可执行入口。"""
    assert callable(auto_confirm_job.main)
    assert callable(auto_confirm_job.run_once)


async def test_script_passes_config_threshold_to_service(monkeypatch) -> None:
    """脚本按配置里的阈值调 service（不硬编码）。"""
    calls = []

    async def _fake_auto_confirm(session, *, threshold_hours=None):
        calls.append(threshold_hours)
        return 3

    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

    monkeypatch.setattr(auto_confirm_job, "auto_confirm_expired", _fake_auto_confirm)
    monkeypatch.setattr(auto_confirm_job, "session_factory", lambda: _FakeSession())

    count = await auto_confirm_job.run_once()

    assert count == 3
    assert calls == [settings.auto_confirm_threshold_hours]


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
    """种一个服务商、两个账号、一个师傅、三笔「待确认」订单。

    其中两笔的 ``updated_at`` 设在很久以前（超时），一笔是刚刚的（没超时）。
    """
    maker = async_sessionmaker(db, class_=AsyncSession, expire_on_commit=False)
    tomorrow = date.today() + timedelta(days=1)
    now = datetime.now(timezone.utc)
    async with maker() as session:
        session.add(
            ServiceProvider(
                id=MY_PROVIDER_ID, name="我的服务商", contact_phone="13800000001"
            )
        )
        await session.flush()

        session.add_all(
            [
                User(id=CUSTOMER_USER_ID, phone="13900000001", role=UserRole.USER),
                User(id=MY_MASTER_USER_ID, phone="13900000002", role=UserRole.MASTER),
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
                base_price=BASE_PRICE,
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

        session.add(
            Master(
                id=MY_MASTER_ID,
                provider_id=MY_PROVIDER_ID,
                user_id=MY_MASTER_USER_ID,
                real_name="张师傅",
                status=MasterStatus.ACTIVE,
            )
        )
        await session.flush()

        def _order(order_id: int, order_no: str, updated_at: datetime) -> Order:
            return Order(
                id=order_id,
                order_no=order_no,
                user_id=CUSTOMER_USER_ID,
                provider_id=MY_PROVIDER_ID,
                master_id=MY_MASTER_ID,
                address_id=3,
                item_id=2,
                slot_id=4,
                amount=BASE_PRICE,
                status=OrderStatus.PENDING_CONFIRM,
                pay_status=PayStatus.PAID,
                paid_at=now,
                dispatched_at=now,
                accepted_at=now,
                updated_at=updated_at,
            )

        session.add_all(
            [
                _order(
                    TIMED_OUT_ORDER_ID_1,
                    TIMED_OUT_ORDER_NO_1,
                    now - timedelta(hours=30),
                ),
                _order(
                    TIMED_OUT_ORDER_ID_2,
                    TIMED_OUT_ORDER_NO_2,
                    now - timedelta(hours=48),
                ),
                _order(FRESH_ORDER_ID, FRESH_ORDER_NO, now),
            ]
        )
        await session.flush()
        await session.commit()
    return True


def _maker(db) -> async_sessionmaker:
    return async_sessionmaker(db, class_=AsyncSession, expire_on_commit=False)


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


async def _run(db, *, threshold_hours: int | None = None) -> int:
    maker = _maker(db)
    async with maker() as session:
        return await auto_confirm_expired(session, threshold_hours=threshold_hours)


# ---------------------------------------------------------------------
# 1. 只确认超时的订单
# ---------------------------------------------------------------------


@pytest.mark.integration
async def test_auto_confirm_confirms_only_timed_out_orders(db, seeded) -> None:
    """两笔超时 + 一笔未超时 -> 只确认两笔，未超时的那笔不动。"""
    count = await _run(db, threshold_hours=24)

    assert count == 2

    for order_id in (TIMED_OUT_ORDER_ID_1, TIMED_OUT_ORDER_ID_2):
        order = await _order_of(db, order_id)
        assert order.status == OrderStatus.COMPLETED
        assert order.auto_confirmed is True
        assert order.completed_at is not None

    # 没超时的还停在「待确认」，也没被标成自动确认
    fresh = await _order_of(db, FRESH_ORDER_ID)
    assert fresh.status == OrderStatus.PENDING_CONFIRM
    assert fresh.auto_confirmed is False
    assert fresh.completed_at is None
    assert await _logs_of(db, FRESH_ORDER_ID) == []


@pytest.mark.integration
async def test_auto_confirm_writes_system_status_log(db, seeded) -> None:
    """自动确认同样留痕：操作方是系统，不是任何人。"""
    await _run(db, threshold_hours=24)

    logs = await _logs_of(db, TIMED_OUT_ORDER_ID_1)
    assert len(logs) == 1
    assert logs[0].from_status == OrderStatus.PENDING_CONFIRM
    assert logs[0].to_status == OrderStatus.COMPLETED
    assert logs[0].operator_type == OperatorType.SYSTEM
    assert logs[0].operator_id == SYSTEM_OPERATOR_ID
    assert logs[0].operator_id == 0
    assert logs[0].reason == AUTO_CONFIRM_REASON
    assert logs[0].reason == "超时自动确认"


# ---------------------------------------------------------------------
# 2. 幂等
# ---------------------------------------------------------------------


@pytest.mark.integration
async def test_auto_confirm_is_idempotent(db, seeded) -> None:
    """连跑两次：第二次转 0 笔，也不会多写日志。

    这是 cron 每天跑一次的前提——重复执行不能把同一笔订单确认两遍。
    """
    first = await _run(db, threshold_hours=24)
    assert first == 2

    second = await _run(db, threshold_hours=24)
    assert second == 0

    for order_id in (TIMED_OUT_ORDER_ID_1, TIMED_OUT_ORDER_ID_2):
        order = await _order_of(db, order_id)
        assert order.status == OrderStatus.COMPLETED
        # 留痕仍然只有一条：没有重复确认
        assert len(await _logs_of(db, order_id)) == 1


# ---------------------------------------------------------------------
# 3. 条件 UPDATE：rowcount == 0 跳过不报错
# ---------------------------------------------------------------------


@pytest.mark.integration
async def test_confirm_one_skips_order_that_is_not_pending_confirm(db, seeded) -> None:
    """订单不在「待确认」-> 条件 UPDATE 不命中，跳过、不报错。

    「这一笔刚被别人确认了」不是错误，只是没轮到我们。
    """
    maker = _maker(db)
    async with maker() as session:
        fresh = await _order_of(db, FRESH_ORDER_ID)
        assert fresh.status == OrderStatus.PENDING_CONFIRM

        # 手工把这笔改成别的状态，模拟「等锁期间被人改走」
        async with maker() as updater:
            await updater.execute(
                Order.__table__.update()
                .where(Order.id == FRESH_ORDER_ID)
                .values(status=OrderStatus.COMPLETED)
            )
            await updater.commit()

        result = await _confirm_one(session, order_id=FRESH_ORDER_ID)

    assert result is False
    order = await _order_of(db, FRESH_ORDER_ID)
    assert order.status == OrderStatus.COMPLETED
    assert order.auto_confirmed is False


# ---------------------------------------------------------------------
# 4. 单笔失败不拖垮整批
# ---------------------------------------------------------------------


@pytest.mark.integration
async def test_single_order_failure_does_not_stop_the_batch(
    db, seeded, monkeypatch, caplog
) -> None:
    """一笔失败 -> 记日志、继续下一笔，不抛异常给调用方。

    定时任务因为一笔脏数据整批失败，比漏掉一笔更糟。
    """
    original = auto_confirm_module._confirm_one

    async def _fake_confirm_one(session, *, order_id):
        if order_id == TIMED_OUT_ORDER_ID_1:
            raise RuntimeError("模拟这一笔坏了")
        return await original(session, order_id=order_id)

    monkeypatch.setattr(auto_confirm_module, "_confirm_one", _fake_confirm_one)

    with caplog.at_level("ERROR", logger="app.services.auto_confirm"):
        count = await _run(db, threshold_hours=24)

    # 坏的那笔没成功，另外一笔照常确认（调用方拿到的是成功笔数，不是异常）
    assert count == 1

    failed = await _order_of(db, TIMED_OUT_ORDER_ID_1)
    assert failed.status == OrderStatus.PENDING_CONFIRM
    assert await _logs_of(db, TIMED_OUT_ORDER_ID_1) == []

    ok = await _order_of(db, TIMED_OUT_ORDER_ID_2)
    assert ok.status == OrderStatus.COMPLETED

    # 失败被记了日志（含订单 id），不是悄悄吞掉
    assert "order_id={}".format(TIMED_OUT_ORDER_ID_1) in caplog.text
