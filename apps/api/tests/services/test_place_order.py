"""下单 service 的测试。

分两部分：
- 单元测试：用最小 AsyncSession 替身，不依赖数据库；
- 集成测试：需要真实 PostgreSQL，通过 TEST_DATABASE_URL 指定数据库地址，
  未设置时自动跳过（这样没有 PG 的环境也能跑整套测试）。
"""
from __future__ import annotations

import asyncio
import inspect
import os
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import Select, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.services.place_order as place_order_module
from app.domain.slot_rule import SlotNotReservableError
from app.models.address import Address
from app.models.base import Base
from app.models.catalog import ServiceCategory, ServiceItem
from app.models.enums import CatalogStatus, OperatorType, OrderStatus, PayStatus
from app.models.order import Order, OrderStatusLog
from app.models.schedule_slot import ScheduleSlot
from app.models.user import User
from app.services.errors import (
    AddressNotFoundError,
    ItemInactiveError,
    ItemNotFoundError,
    OrderNoConflictError,
    PlaceOrderError,
    SlotItemMismatchError,
    SlotNotFoundError,
    SlotNotInFutureError,
)
from app.services.place_order import place_order

# =====================================================================
# 单元测试：最小 AsyncSession 替身
# =====================================================================


class _FakeResult:
    """只实现 service 用到的几个取数方法。"""

    def __init__(self, rows=(), rowcount: int | None = None) -> None:
        self._rows = list(rows)
        self.rowcount = rowcount

    def first(self):
        return self._rows[0] if self._rows else None

    def one_or_none(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return list(self._rows)


class _FakeTransaction:
    """模拟 session.begin() 的事务上下文。"""

    def __init__(self, session: "FakeSession") -> None:
        self._session = session

    async def __aenter__(self):
        self._session.begin_count += 1
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if exc_type is None:
            self._session.commit_count += 1
        else:
            self._session.rollback_count += 1
        return False  # 不吞异常


class FakeSession:
    """只实现 place_order 用到的那几个方法的 AsyncSession 替身。"""

    def __init__(
        self,
        *,
        select_results=None,
        update_results=None,
        flush_errors=None,
    ) -> None:
        self._select_results = list(select_results or [])
        self._update_results = list(update_results or [])
        self._flush_errors = list(flush_errors or [])
        self.statements = []
        self.added = []
        self.flush_count = 0
        self.rollback_count = 0
        self.commit_count = 0
        self.begin_count = 0

    async def execute(self, stmt):
        self.statements.append(stmt)
        if isinstance(stmt, Select):
            if not self._select_results:
                raise AssertionError("意料之外的 SELECT：{}".format(stmt))
            return self._select_results.pop(0)
        if not self._update_results:
            raise AssertionError("意料之外的 UPDATE：{}".format(stmt))
        return self._update_results.pop(0)

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        self.flush_count += 1
        if self._flush_errors:
            error = self._flush_errors.pop(0)
            if error is not None:
                raise error

    async def rollback(self) -> None:
        self.rollback_count += 1

    def begin(self) -> _FakeTransaction:
        return _FakeTransaction(self)


class _FakeOrigError(Exception):
    """模拟 asyncpg 的数据库异常：带 sqlstate 与 constraint_name。"""

    def __init__(self, sqlstate: str, constraint_name: str | None = None) -> None:
        super().__init__("fake db error {}".format(sqlstate))
        self.sqlstate = sqlstate
        self.constraint_name = constraint_name


def _order_no_violation() -> IntegrityError:
    return IntegrityError(
        "INSERT INTO order ...",
        {},
        _FakeOrigError("23505", "uq_order_order_no"),
    )


def _foreign_key_violation() -> IntegrityError:
    return IntegrityError(
        "INSERT INTO order ...",
        {},
        _FakeOrigError("23503", "fk_order_slot_id"),
    )


UNIT_USER_ID = 1
UNIT_ITEM_ID = 2
UNIT_SLOT_ID = 3
UNIT_ADDRESS_ID = 4
UNIT_BASE_PRICE = Decimal("100.00")
UNIT_SLOT_DATE = date(2099, 1, 1)
UNIT_SLOT_START = time(9, 0)


def _unit_select_results() -> list[_FakeResult]:
    """校验阶段的三个 SELECT 的返回值（地址 / 服务项 / 时段）。"""
    return [
        _FakeResult([(UNIT_ADDRESS_ID,)]),
        _FakeResult([(UNIT_BASE_PRICE, CatalogStatus.ACTIVE)]),
        _FakeResult(
            [
                (
                    UNIT_SLOT_ID,
                    UNIT_ITEM_ID,
                    UNIT_SLOT_DATE,
                    UNIT_SLOT_START,
                    5,
                    0,
                )
            ]
        ),
    ]


def _unit_session(**kwargs) -> FakeSession:
    kwargs.setdefault("select_results", _unit_select_results())
    kwargs.setdefault("update_results", [_FakeResult(rowcount=1)])
    return FakeSession(**kwargs)


# =====================================================================
# 单元测试
# =====================================================================


def test_exception_hierarchy() -> None:
    """所有下单业务异常都挂在 PlaceOrderError 下。"""
    for error_cls in (
        AddressNotFoundError,
        ItemInactiveError,
        ItemNotFoundError,
        OrderNoConflictError,
        SlotItemMismatchError,
        SlotNotFoundError,
        SlotNotInFutureError,
    ):
        assert issubclass(error_cls, PlaceOrderError)
        assert issubclass(error_cls, Exception)
    assert issubclass(PlaceOrderError, Exception)


def test_signature_accepts_no_business_fields() -> None:
    """入参只允许 user_id / item_id / slot_id / address_id。"""
    params = inspect.signature(place_order).parameters
    assert list(params) == ["session", "user_id", "item_id", "slot_id", "address_id"]
    for forbidden in ("amount", "order_no", "status", "provider_id", "master_id"):
        assert forbidden not in params


async def test_place_order_success() -> None:
    """首轮成功：写一笔订单 + 一条状态日志。"""
    session = _unit_session()
    order = await place_order(
        session,
        user_id=UNIT_USER_ID,
        item_id=UNIT_ITEM_ID,
        slot_id=UNIT_SLOT_ID,
        address_id=UNIT_ADDRESS_ID,
    )

    assert order.status == OrderStatus.PENDING_PAY
    assert order.pay_status == PayStatus.UNPAID
    assert order.provider_id is None
    assert order.master_id is None
    assert order.user_id == UNIT_USER_ID
    assert order.item_id == UNIT_ITEM_ID
    assert order.slot_id == UNIT_SLOT_ID
    assert order.address_id == UNIT_ADDRESS_ID
    assert order.amount == Decimal("100.00")
    assert order.order_no.startswith("OTO")
    assert len(order.order_no) == 17

    assert session.begin_count == 1
    assert session.commit_count == 1
    # 校验阶段结束后显式回滚了只读事务
    assert session.rollback_count == 1

    logs = [obj for obj in session.added if isinstance(obj, OrderStatusLog)]
    assert len(logs) == 1
    assert logs[0].from_status is None
    assert logs[0].to_status == OrderStatus.PENDING_PAY
    assert logs[0].operator_type == OperatorType.USER
    assert logs[0].operator_id == UNIT_USER_ID
    assert logs[0].reason == "用户下单"


async def test_place_order_retries_after_order_no_conflict() -> None:
    """首轮 order_no 唯一冲突 -> 回滚 -> 次轮换号成功。"""
    session = _unit_session(
        update_results=[_FakeResult(rowcount=1), _FakeResult(rowcount=1)],
        flush_errors=[_order_no_violation(), None],
    )
    order = await place_order(
        session,
        user_id=UNIT_USER_ID,
        item_id=UNIT_ITEM_ID,
        slot_id=UNIT_SLOT_ID,
        address_id=UNIT_ADDRESS_ID,
    )

    assert order.order_no.startswith("OTO")
    assert session.begin_count == 2  # 两轮事务
    assert session.commit_count == 1  # 只有次轮提交
    assert session.rollback_count == 2  # 校验阶段 1 次 + 冲突轮 1 次


async def test_place_order_raises_after_max_attempts() -> None:
    """三轮全冲突 -> OrderNoConflictError。"""
    session = _unit_session(
        update_results=[
            _FakeResult(rowcount=1),
            _FakeResult(rowcount=1),
            _FakeResult(rowcount=1),
        ],
        flush_errors=[
            _order_no_violation(),
            _order_no_violation(),
            _order_no_violation(),
        ],
    )
    with pytest.raises(OrderNoConflictError):
        await place_order(
            session,
            user_id=UNIT_USER_ID,
            item_id=UNIT_ITEM_ID,
            slot_id=UNIT_SLOT_ID,
            address_id=UNIT_ADDRESS_ID,
        )

    assert session.begin_count == 3
    assert session.commit_count == 0
    # 校验阶段 1 次 + 三轮冲突各 1 次
    assert session.rollback_count == 4


async def test_slot_not_reservable_exits_immediately() -> None:
    """重试轮次里库存不足：立即退出循环，不重试。"""
    select_results = _unit_select_results()
    # 条件 UPDATE 影响 0 行后，service 会同事务内重查 capacity/used
    select_results.append(_FakeResult([(5, 5)]))
    session = _unit_session(
        select_results=select_results,
        update_results=[_FakeResult(rowcount=0)],
    )
    with pytest.raises(SlotNotReservableError):
        await place_order(
            session,
            user_id=UNIT_USER_ID,
            item_id=UNIT_ITEM_ID,
            slot_id=UNIT_SLOT_ID,
            address_id=UNIT_ADDRESS_ID,
        )

    assert session.begin_count == 1  # 只跑了一轮，没有重试
    assert session.commit_count == 0


async def test_slot_missing_exits_immediately() -> None:
    """重试轮次里时段消失：立即退出循环，不重试。"""
    select_results = _unit_select_results()
    select_results.append(_FakeResult([]))  # 重查不到该时段
    session = _unit_session(
        select_results=select_results,
        update_results=[_FakeResult(rowcount=0)],
    )
    with pytest.raises(SlotNotFoundError):
        await place_order(
            session,
            user_id=UNIT_USER_ID,
            item_id=UNIT_ITEM_ID,
            slot_id=UNIT_SLOT_ID,
            address_id=UNIT_ADDRESS_ID,
        )
    assert session.begin_count == 1


async def test_other_integrity_error_does_not_retry() -> None:
    """非 order_no 的完整性冲突（如外键）立即转业务异常，不重试。"""
    session = _unit_session(
        update_results=[_FakeResult(rowcount=1)],
        flush_errors=[_foreign_key_violation()],
    )
    with pytest.raises(PlaceOrderError) as excinfo:
        await place_order(
            session,
            user_id=UNIT_USER_ID,
            item_id=UNIT_ITEM_ID,
            slot_id=UNIT_SLOT_ID,
            address_id=UNIT_ADDRESS_ID,
        )
    assert not isinstance(excinfo.value, OrderNoConflictError)
    assert session.begin_count == 1  # 没有重试
    assert session.commit_count == 0


async def test_validation_reads_scalars_only() -> None:
    """硬伤1：校验阶段只 select 标量列，不持有 ORM 实体。

    校验结束要 rollback，session 内的持久化对象会过期，
    async 下访问其属性会触发 lazy load（MissingGreenlet）。
    """
    session = _unit_session()
    await place_order(
        session,
        user_id=UNIT_USER_ID,
        item_id=UNIT_ITEM_ID,
        slot_id=UNIT_SLOT_ID,
        address_id=UNIT_ADDRESS_ID,
    )
    selects = [s for s in session.statements if isinstance(s, Select)]
    assert selects, "应当有校验阶段的 SELECT"
    for stmt in selects:
        for description in stmt.column_descriptions:
            # expr 是映射类本身，说明这条 SELECT 会加载 ORM 实体；
            # 只 select 列时 expr 是列，拿到的是标量
            assert not isinstance(description["expr"], type), (
                "校验阶段不得 select ORM 实体：{}".format(stmt)
            )


async def test_address_not_owned_is_rejected() -> None:
    """地址不属于当前用户 -> AddressNotFoundError（不区分不存在 / 不属于你）。"""
    select_results = _unit_select_results()
    select_results[0] = _FakeResult([])  # 查不到该用户的地址
    session = _unit_session(select_results=select_results)
    with pytest.raises(AddressNotFoundError) as excinfo:
        await place_order(
            session,
            user_id=UNIT_USER_ID,
            item_id=UNIT_ITEM_ID,
            slot_id=UNIT_SLOT_ID,
            address_id=UNIT_ADDRESS_ID,
        )
    # 消息不得泄漏归属信息
    assert str(UNIT_ADDRESS_ID) in str(excinfo.value)
    assert "user" not in str(excinfo.value).lower()
    assert session.begin_count == 0  # 校验失败，不开事务


async def test_item_not_found_is_rejected() -> None:
    select_results = _unit_select_results()
    select_results[1] = _FakeResult([])
    session = _unit_session(select_results=select_results)
    with pytest.raises(ItemNotFoundError):
        await place_order(
            session,
            user_id=UNIT_USER_ID,
            item_id=UNIT_ITEM_ID,
            slot_id=UNIT_SLOT_ID,
            address_id=UNIT_ADDRESS_ID,
        )
    assert session.begin_count == 0


async def test_item_inactive_is_rejected() -> None:
    select_results = _unit_select_results()
    select_results[1] = _FakeResult([(UNIT_BASE_PRICE, CatalogStatus.INACTIVE)])
    session = _unit_session(select_results=select_results)
    with pytest.raises(ItemInactiveError):
        await place_order(
            session,
            user_id=UNIT_USER_ID,
            item_id=UNIT_ITEM_ID,
            slot_id=UNIT_SLOT_ID,
            address_id=UNIT_ADDRESS_ID,
        )
    assert session.begin_count == 0


async def test_slot_not_found_is_rejected() -> None:
    select_results = _unit_select_results()
    select_results[2] = _FakeResult([])
    session = _unit_session(select_results=select_results)
    with pytest.raises(SlotNotFoundError):
        await place_order(
            session,
            user_id=UNIT_USER_ID,
            item_id=UNIT_ITEM_ID,
            slot_id=UNIT_SLOT_ID,
            address_id=UNIT_ADDRESS_ID,
        )
    assert session.begin_count == 0


async def test_slot_item_mismatch_is_rejected() -> None:
    select_results = _unit_select_results()
    select_results[2] = _FakeResult(
        [(UNIT_SLOT_ID, UNIT_ITEM_ID + 100, UNIT_SLOT_DATE, UNIT_SLOT_START, 5, 0)]
    )
    session = _unit_session(select_results=select_results)
    with pytest.raises(SlotItemMismatchError):
        await place_order(
            session,
            user_id=UNIT_USER_ID,
            item_id=UNIT_ITEM_ID,
            slot_id=UNIT_SLOT_ID,
            address_id=UNIT_ADDRESS_ID,
        )
    assert session.begin_count == 0


async def test_slot_in_past_is_rejected() -> None:
    select_results = _unit_select_results()
    past = datetime.now(timezone.utc) - timedelta(days=1)
    select_results[2] = _FakeResult(
        [(UNIT_SLOT_ID, UNIT_ITEM_ID, past.date(), past.time(), 5, 0)]
    )
    session = _unit_session(select_results=select_results)
    with pytest.raises(SlotNotInFutureError):
        await place_order(
            session,
            user_id=UNIT_USER_ID,
            item_id=UNIT_ITEM_ID,
            slot_id=UNIT_SLOT_ID,
            address_id=UNIT_ADDRESS_ID,
        )
    assert session.begin_count == 0


# =====================================================================
# 集成测试：需要真实 PostgreSQL
# =====================================================================

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


@dataclass
class Seed:
    user_id: int
    item_id: int
    slot_id: int
    address_id: int
    base_price: Decimal
    capacity: int


@pytest.fixture
async def db():
    """每个测试一块干净的库。"""
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
async def seeded(db) -> Seed:
    maker = async_sessionmaker(db, class_=AsyncSession, expire_on_commit=False)
    tomorrow = date.today() + timedelta(days=1)
    async with maker() as session:
        # 模型层没有 relationship，SQLAlchemy 的 flush 顺序按 mapper 类名字母序
        # （不是外键依赖序），所以这里按依赖顺序逐个 flush，避免外键违例
        session.add(User(id=1, phone="13800000001"))
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
                id=4,
                user_id=1,
                contact="张三",
                phone="13800000001",
                region="北京",
                detail="某街道 1 号",
            )
        )
        await session.flush()
        session.add(
            ScheduleSlot(
                id=3,
                item_id=2,
                date=tomorrow,
                start_time=time(9, 0),
                end_time=time(12, 0),
                capacity=5,
            )
        )
        await session.commit()
    return Seed(
        user_id=1,
        item_id=2,
        slot_id=3,
        address_id=4,
        base_price=Decimal("100.00"),
        capacity=5,
    )


def _maker(db, class_=AsyncSession) -> async_sessionmaker:
    return async_sessionmaker(db, class_=class_, expire_on_commit=False)


async def test_integration_place_order_success(db, seeded) -> None:
    """正常下单：扣库存 + 落订单 + 写状态日志。"""
    maker = _maker(db)
    async with maker() as session:
        order = await place_order(
            session,
            user_id=seeded.user_id,
            item_id=seeded.item_id,
            slot_id=seeded.slot_id,
            address_id=seeded.address_id,
        )
        assert order.id is not None
        assert order.amount == seeded.base_price
        assert order.status == OrderStatus.PENDING_PAY

    async with maker() as session:
        orders = (await session.execute(select(Order))).scalars().all()
        assert len(orders) == 1
        assert orders[0].slot_id == seeded.slot_id
        assert orders[0].provider_id is None
        assert orders[0].master_id is None

        logs = (await session.execute(select(OrderStatusLog))).scalars().all()
        assert len(logs) == 1
        assert logs[0].from_status is None
        assert logs[0].to_status == OrderStatus.PENDING_PAY
        assert logs[0].operator_type == OperatorType.USER
        assert logs[0].operator_id == seeded.user_id
        assert logs[0].reason == "用户下单"

        used = (
            await session.execute(
                select(ScheduleSlot.used).where(ScheduleSlot.id == seeded.slot_id)
            )
        ).scalar_one()
        assert used == 1


async def test_integration_slot_not_reservable_leaves_no_order(db, seeded) -> None:
    """库存不足：条件 UPDATE 影响 0 行 -> SlotNotReservableError，无残行。"""
    maker = _maker(db)
    async with maker() as session:
        await session.execute(
            update(ScheduleSlot)
            .where(ScheduleSlot.id == seeded.slot_id)
            .values(used=seeded.capacity)
        )
        await session.commit()

    async with maker() as session:
        with pytest.raises(SlotNotReservableError):
            await place_order(
                session,
                user_id=seeded.user_id,
                item_id=seeded.item_id,
                slot_id=seeded.slot_id,
                address_id=seeded.address_id,
            )

    async with maker() as session:
        count = (
            await session.execute(select(func.count()).select_from(Order))
        ).scalar_one()
        assert count == 0
        used = (
            await session.execute(
                select(ScheduleSlot.used).where(ScheduleSlot.id == seeded.slot_id)
            )
        ).scalar_one()
        assert used == seeded.capacity  # 库存未被改动


class _FailingFlushSession(AsyncSession):
    """模拟订单写入失败。"""

    async def flush(self, *args, **kwargs):
        raise RuntimeError("模拟订单 insert 失败")


async def test_integration_rolls_back_stock_on_insert_failure(db, seeded) -> None:
    """订单写入失败：库存扣减也回滚，used 恢复原值。"""
    maker = _maker(db, class_=_FailingFlushSession)
    with pytest.raises(RuntimeError):
        async with maker() as session:
            await place_order(
                session,
                user_id=seeded.user_id,
                item_id=seeded.item_id,
                slot_id=seeded.slot_id,
                address_id=seeded.address_id,
            )

    maker = _maker(db)
    async with maker() as session:
        used = (
            await session.execute(
                select(ScheduleSlot.used).where(ScheduleSlot.id == seeded.slot_id)
            )
        ).scalar_one()
        assert used == 0  # 扣减已回滚
        count = (
            await session.execute(select(func.count()).select_from(Order))
        ).scalar_one()
        assert count == 0


async def test_integration_retries_on_order_no_conflict(db, seeded, monkeypatch) -> None:
    """注入重复 order_no：首轮冲突 -> 重试换号 -> 成功。"""
    maker = _maker(db)
    duplicate_no = "OTO20990101000001"
    async with maker() as session:
        session.add(
            Order(
                order_no=duplicate_no,
                user_id=seeded.user_id,
                address_id=seeded.address_id,
                item_id=seeded.item_id,
                slot_id=seeded.slot_id,
                amount=seeded.base_price,
            )
        )
        await session.commit()

    numbers = iter([duplicate_no, "OTO20990101000002"])
    monkeypatch.setattr(
        place_order_module, "generate_order_no", lambda **kwargs: next(numbers)
    )

    async with maker() as session:
        order = await place_order(
            session,
            user_id=seeded.user_id,
            item_id=seeded.item_id,
            slot_id=seeded.slot_id,
            address_id=seeded.address_id,
        )
        assert order.order_no == "OTO20990101000002"


async def test_integration_raises_when_order_no_always_conflicts(
    db, seeded, monkeypatch
) -> None:
    """订单号一直冲突：重试到上限 -> OrderNoConflictError。"""
    maker = _maker(db)
    duplicate_no = "OTO20990101000003"
    async with maker() as session:
        session.add(
            Order(
                order_no=duplicate_no,
                user_id=seeded.user_id,
                address_id=seeded.address_id,
                item_id=seeded.item_id,
                slot_id=seeded.slot_id,
                amount=seeded.base_price,
            )
        )
        await session.commit()

    monkeypatch.setattr(
        place_order_module, "generate_order_no", lambda **kwargs: duplicate_no
    )

    with pytest.raises(OrderNoConflictError):
        async with maker() as session:
            await place_order(
                session,
                user_id=seeded.user_id,
                item_id=seeded.item_id,
                slot_id=seeded.slot_id,
                address_id=seeded.address_id,
            )

    async with maker() as session:
        used = (
            await session.execute(
                select(ScheduleSlot.used).where(ScheduleSlot.id == seeded.slot_id)
            )
        ).scalar_one()
        assert used == 0  # 每轮都回滚了


async def test_integration_concurrent_orders_do_not_oversell(db, seeded) -> None:
    """并发下单不超卖：N 个并发抢 capacity 个名额，成功数恰好等于 capacity。"""
    concurrency = 10
    capacity = 3
    maker = _maker(db)
    async with maker() as session:
        await session.execute(
            update(ScheduleSlot)
            .where(ScheduleSlot.id == seeded.slot_id)
            .values(capacity=capacity, used=0)
        )
        await session.commit()

    async def attempt() -> str:
        async with maker() as session:
            try:
                await place_order(
                    session,
                    user_id=seeded.user_id,
                    item_id=seeded.item_id,
                    slot_id=seeded.slot_id,
                    address_id=seeded.address_id,
                )
                return "ok"
            except SlotNotReservableError:
                return "full"

    results = await asyncio.gather(*[attempt() for _ in range(concurrency)])

    assert results.count("ok") == capacity
    assert results.count("full") == concurrency - capacity

    async with maker() as session:
        used = (
            await session.execute(
                select(ScheduleSlot.used).where(ScheduleSlot.id == seeded.slot_id)
            )
        ).scalar_one()
        assert used == capacity
        orders = (
            await session.execute(select(func.count()).select_from(Order))
        ).scalar_one()
        assert orders == capacity
