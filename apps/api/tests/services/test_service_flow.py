"""服务流转 service（开工 / 完工 / 客户确认完成）的测试。

分两类：

- **单元测试**（不碰数据库）：service 的签名边界（master_id / user_id 传不进来）、
  角色守卫、内部一致性校验、异常映射；
- **集成测试**（需要真实 PostgreSQL）：真的走 service -> 数据库，
  验证开工、完工、确认、并发推进、以及「不暴露存在性」。

集成测试用的数据库是 TEST_DATABASE_URL 指向的独立测试库
（集成 fixture 每次 drop_all + create_all，绝不碰开发库）。

这一层没有 router（接口是 T-10b 的活），所以这里直接调 service。
"""
from __future__ import annotations

import asyncio
import inspect
import os
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.services.service_flow as service_flow_module
from tests.support import business_today
from app.api.v1.errors import status_for
from app.core.auth import CurrentUser
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
from app.services.errors import (
    OrderNotFoundError,
    ServiceFlowError,
    ServiceFlowForbiddenError,
    ServiceFlowInvariantError,
)
from app.services.service_flow import (
    _assert_written_state,
    confirm_complete,
    finish_service,
    start_service,
)
from support import Rendezvous, RendezvousSession

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

# ---------------------------------------------------------------------
# 种子数据里的 id
# ---------------------------------------------------------------------

# 服务商
MY_PROVIDER_ID = 1
OTHER_PROVIDER_ID = 7

# 师傅
MY_MASTER_ID = 1  # 本商师傅
OTHER_MASTER_ID = 8  # 别家师傅

# 账号
CUSTOMER_USER_ID = 1  # 客户（我的订单的主人）
OTHER_CUSTOMER_USER_ID = 2  # 另一个客户
MY_MASTER_USER_ID = 3  # 师傅账号（master 表里有身份）
OTHER_MASTER_USER_ID = 4  # 别家师傅账号
NO_MASTER_USER_ID = 5  # 角色是 MASTER，但 master 表里没有身份

# 订单
ACCEPTED_MY_ORDER_ID = 1  # 我的师傅已接单 -> 可以开工
ACCEPTED_OTHER_ORDER_ID = 2  # 别家师傅的已接单订单
IN_SERVICE_MY_ORDER_ID = 3  # 我师傅的服务中订单 -> 可以完工
IN_SERVICE_OTHER_ORDER_ID = 4  # 别家师傅的服务中订单
PENDING_CONFIRM_MY_ORDER_ID = 5  # 我的订单，待我确认
PENDING_CONFIRM_OTHER_ORDER_ID = 6  # 别人的订单，待别人确认
WRONG_STATE_ORDER_ID = 7  # 还停在「待接单」——状态不对

BASE_PRICE = Decimal("100.00")

ACCEPTED_MY_ORDER_NO = "OTO20260201000001"
ACCEPTED_OTHER_ORDER_NO = "OTO20260201000002"
IN_SERVICE_MY_ORDER_NO = "OTO20260201000003"
IN_SERVICE_OTHER_ORDER_NO = "OTO20260201000004"
PENDING_CONFIRM_MY_ORDER_NO = "OTO20260201000005"
PENDING_CONFIRM_OTHER_ORDER_NO = "OTO20260201000006"
WRONG_STATE_ORDER_NO = "OTO20260201000007"
MISSING_ORDER_NO = "OTO20260201009999"


def _my_master() -> CurrentUser:
    return CurrentUser(user_id=MY_MASTER_USER_ID, role=UserRole.MASTER, provider_id=None)


def _other_master() -> CurrentUser:
    return CurrentUser(user_id=OTHER_MASTER_USER_ID, role=UserRole.MASTER, provider_id=None)


def _customer() -> CurrentUser:
    return CurrentUser(user_id=CUSTOMER_USER_ID, role=UserRole.USER, provider_id=None)


class _ExplodingSession:
    """碰一下就炸的会话。

    用来证明「角色不对时，service 根本不会去碰数据库」：
    失败发生在碰订单之前，不泄露任何订单信息。
    """

    def __getattr__(self, name):
        raise AssertionError("角色不对时不该碰数据库：{}".format(name))


# =====================================================================
# 单元测试：签名边界、角色守卫、异常映射
# =====================================================================


def test_service_signatures_take_no_identity_params() -> None:
    """三个 service 的签名里都没有 master_id / user_id / order_id。

    身份只能从 CurrentUser 推出来：师傅身份查 master 表，客户身份就是
    current.user_id。这是「身份不从入参取」的结构性保证——
    以后谁想加这个参数，测试先红。
    """
    for func in (start_service, finish_service, confirm_complete):
        parameters = inspect.signature(func).parameters
        assert "master_id" not in parameters
        assert "user_id" not in parameters
        assert "order_id" not in parameters
        assert "order_no" in parameters
        assert "current" in parameters


def test_module_uses_conditional_update() -> None:
    """写订单用的是条件 UPDATE + RETURNING，不是读-改-写。

    「读-改-写」在源码里的样子是：先 select 出 order，再对它的属性赋值。
    这里断言写操作走的是 update(Order) ... .returning(Order.id)，
    与 dispatch / master_action 同一套写法。
    """
    source = inspect.getsource(service_flow_module)
    assert "update(Order)" in source
    assert ".returning(Order.id)" in source
    assert "result.rowcount" not in source  # 用 RETURNING 判命中，不读 rowcount


def test_start_and_finish_use_master_id_predicate() -> None:
    """开工 / 完工的 WHERE 谓词里带着 master_id（归属限定）。"""
    source = inspect.getsource(service_flow_module)
    assert "owner_column=Order.master_id" in source


def test_confirm_uses_user_id_predicate() -> None:
    """确认完成的 WHERE 谓词里带着 user_id（归属限定）。"""
    source = inspect.getsource(service_flow_module)
    assert "owner_column=Order.user_id" in source


def test_reason_constants() -> None:
    """留在状态流转日志里的原因固定。"""
    assert service_flow_module.START_REASON == "师傅开工"
    assert service_flow_module.FINISH_REASON == "师傅完工"
    assert service_flow_module.CONFIRM_REASON == "客户确认完成"


def test_operator_types_are_master_and_user() -> None:
    """开工 / 完工是师傅侧动作（MASTER），确认完成是用户侧动作（USER）。"""
    source = inspect.getsource(service_flow_module)
    assert "OperatorType.MASTER" in source
    assert "OperatorType.USER" in source
    # 确认完成必须用 USER，不能是 MASTER
    confirm_source = inspect.getsource(confirm_complete)
    assert "OperatorType.USER" in confirm_source
    assert "OperatorType.MASTER" not in confirm_source


def test_state_machine_is_used() -> None:
    """三个动作都必须过状态机（assert_transition）。"""
    source = inspect.getsource(service_flow_module)
    assert source.count("assert_transition(") == 3  # 三个动作各一次
    for pair in (
        "assert_transition(OrderStatus.ACCEPTED, OrderStatus.IN_SERVICE)",
        "assert_transition(OrderStatus.IN_SERVICE, OrderStatus.PENDING_CONFIRM)",
        "assert_transition(OrderStatus.PENDING_CONFIRM, OrderStatus.COMPLETED)",
    ):
        assert pair in source


async def test_start_rejects_non_master_role_without_touching_db() -> None:
    """普通用户不能开工，而且在碰数据库之前就被挡住。"""
    with pytest.raises(ServiceFlowForbiddenError):
        await start_service(
            _ExplodingSession(), current=_customer(), order_no=ACCEPTED_MY_ORDER_NO
        )


async def test_finish_rejects_non_master_role_without_touching_db() -> None:
    """普通用户不能完工。"""
    with pytest.raises(ServiceFlowForbiddenError):
        await finish_service(
            _ExplodingSession(), current=_customer(), order_no=IN_SERVICE_MY_ORDER_NO
        )


async def test_confirm_rejects_master_role_without_touching_db() -> None:
    """师傅不能替客户确认完成。"""
    with pytest.raises(ServiceFlowForbiddenError):
        await confirm_complete(
            _ExplodingSession(), current=_my_master(), order_no=PENDING_CONFIRM_MY_ORDER_NO
        )


def test_assert_written_state_passes_when_row_matches() -> None:
    """回读与自己写的一致 -> 不抛。"""
    order = Order(
        id=1,
        order_no=ACCEPTED_MY_ORDER_NO,
        status=OrderStatus.IN_SERVICE,
        master_id=MY_MASTER_ID,
    )
    _assert_written_state(
        order,
        to_status=OrderStatus.IN_SERVICE,
        owner_column=Order.master_id,
        expected_owner_id=MY_MASTER_ID,
    )


def test_assert_written_state_raises_on_inconsistent_row() -> None:
    """本会话写过的行，回读却不是自己写的样子 -> ServiceFlowInvariantError。

    这是服务端 bug（触发器改了值 / 谓词写歪），必须暴露成 500，
    不能伪装成「订单不存在」。
    """
    order = Order(
        id=1,
        order_no=ACCEPTED_MY_ORDER_NO,
        status=OrderStatus.IN_SERVICE,
        master_id=MY_MASTER_ID,
    )
    with pytest.raises(ServiceFlowInvariantError):
        _assert_written_state(
            order,
            to_status=OrderStatus.COMPLETED,
            owner_column=Order.master_id,
            expected_owner_id=MY_MASTER_ID,
        )


def test_service_flow_error_status_mapping() -> None:
    """异常映射：403 / 500 / 400。"""
    assert status_for(ServiceFlowForbiddenError("不能")) == 403
    assert status_for(ServiceFlowInvariantError("坏了")) == 500
    assert status_for(ServiceFlowError("兜底")) == 400
    # 订单不存在复用下单那棵树的 OrderNotFoundError -> 404
    assert status_for(OrderNotFoundError("没有")) == 404


def test_error_tree_is_separate_from_the_other_trees() -> None:
    """服务流转是独立的一棵异常树，不挂在别人下面。

    共用基类会让「下单失败」的兜底文案套到服务流转的错误上。
    """
    assert ServiceFlowError.__bases__ == (Exception,)
    from app.services.errors import DispatchError, MasterActionError, PlaceOrderError

    for other in (PlaceOrderError, DispatchError, MasterActionError):
        assert not issubclass(ServiceFlowError, other)
        assert not issubclass(other, ServiceFlowError)


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
    """种两个服务商、五个账号、两个师傅、七笔订单。

    模型层没有 relationship，SQLAlchemy 的 flush 顺序按 mapper 类名字母序
    （不是外键依赖序），所以这里按依赖顺序逐个 flush，避免外键违例。
    """
    maker = async_sessionmaker(db, class_=AsyncSession, expire_on_commit=False)
    tomorrow = business_today() + timedelta(days=1)
    async with maker() as session:
        session.add_all(
            [
                ServiceProvider(
                    id=MY_PROVIDER_ID, name="我的服务商", contact_phone="13800000001"
                ),
                ServiceProvider(
                    id=OTHER_PROVIDER_ID,
                    name="别家服务商",
                    contact_phone="13800000002",
                ),
            ]
        )
        await session.flush()

        session.add_all(
            [
                User(id=CUSTOMER_USER_ID, phone="13900000001", role=UserRole.USER),
                User(
                    id=OTHER_CUSTOMER_USER_ID,
                    phone="13900000002",
                    role=UserRole.USER,
                ),
                # 师傅账号：师傅的归属权威来源是 master 表，
                # 所以 user.provider_id 必须为空（数据库 CHECK 约束强制）
                User(id=MY_MASTER_USER_ID, phone="13900000003", role=UserRole.MASTER),
                User(id=OTHER_MASTER_USER_ID, phone="13900000004", role=UserRole.MASTER),
                # 角色是 MASTER，但 master 表里没有他的身份 -> 开工时 403
                User(id=NO_MASTER_USER_ID, phone="13900000005", role=UserRole.MASTER),
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

        session.add_all(
            [
                Master(
                    id=MY_MASTER_ID,
                    provider_id=MY_PROVIDER_ID,
                    user_id=MY_MASTER_USER_ID,
                    real_name="张师傅",
                    status=MasterStatus.ACTIVE,
                ),
                Master(
                    id=OTHER_MASTER_ID,
                    provider_id=OTHER_PROVIDER_ID,
                    user_id=OTHER_MASTER_USER_ID,
                    real_name="李师傅",
                    status=MasterStatus.ACTIVE,
                ),
            ]
        )
        await session.flush()

        now = datetime.now(timezone.utc)
        session.add_all(
            [
                # 我的师傅已接单 -> 可以开工
                Order(
                    id=ACCEPTED_MY_ORDER_ID,
                    order_no=ACCEPTED_MY_ORDER_NO,
                    user_id=CUSTOMER_USER_ID,
                    provider_id=MY_PROVIDER_ID,
                    master_id=MY_MASTER_ID,
                    address_id=3,
                    item_id=2,
                    slot_id=4,
                    amount=BASE_PRICE,
                    status=OrderStatus.ACCEPTED,
                    pay_status=PayStatus.PAID,
                    paid_at=now,
                    dispatched_at=now,
                    accepted_at=now,
                ),
                # 别家师傅的已接单订单
                Order(
                    id=ACCEPTED_OTHER_ORDER_ID,
                    order_no=ACCEPTED_OTHER_ORDER_NO,
                    user_id=CUSTOMER_USER_ID,
                    provider_id=OTHER_PROVIDER_ID,
                    master_id=OTHER_MASTER_ID,
                    address_id=3,
                    item_id=2,
                    slot_id=4,
                    amount=BASE_PRICE,
                    status=OrderStatus.ACCEPTED,
                    pay_status=PayStatus.PAID,
                    paid_at=now,
                    dispatched_at=now,
                    accepted_at=now,
                ),
                # 我的师傅的服务中订单 -> 可以完工
                Order(
                    id=IN_SERVICE_MY_ORDER_ID,
                    order_no=IN_SERVICE_MY_ORDER_NO,
                    user_id=CUSTOMER_USER_ID,
                    provider_id=MY_PROVIDER_ID,
                    master_id=MY_MASTER_ID,
                    address_id=3,
                    item_id=2,
                    slot_id=4,
                    amount=BASE_PRICE,
                    status=OrderStatus.IN_SERVICE,
                    pay_status=PayStatus.PAID,
                    paid_at=now,
                    dispatched_at=now,
                    accepted_at=now,
                ),
                # 别家师傅的服务中订单
                Order(
                    id=IN_SERVICE_OTHER_ORDER_ID,
                    order_no=IN_SERVICE_OTHER_ORDER_NO,
                    user_id=CUSTOMER_USER_ID,
                    provider_id=OTHER_PROVIDER_ID,
                    master_id=OTHER_MASTER_ID,
                    address_id=3,
                    item_id=2,
                    slot_id=4,
                    amount=BASE_PRICE,
                    status=OrderStatus.IN_SERVICE,
                    pay_status=PayStatus.PAID,
                    paid_at=now,
                    dispatched_at=now,
                    accepted_at=now,
                ),
                # 我的订单，待我确认
                Order(
                    id=PENDING_CONFIRM_MY_ORDER_ID,
                    order_no=PENDING_CONFIRM_MY_ORDER_NO,
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
                ),
                # 别人的订单，待别人确认
                Order(
                    id=PENDING_CONFIRM_OTHER_ORDER_ID,
                    order_no=PENDING_CONFIRM_OTHER_ORDER_NO,
                    user_id=OTHER_CUSTOMER_USER_ID,
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
                ),
                # 还停在「待接单」——状态不对
                Order(
                    id=WRONG_STATE_ORDER_ID,
                    order_no=WRONG_STATE_ORDER_NO,
                    user_id=CUSTOMER_USER_ID,
                    provider_id=MY_PROVIDER_ID,
                    master_id=MY_MASTER_ID,
                    address_id=3,
                    item_id=2,
                    slot_id=4,
                    amount=BASE_PRICE,
                    status=OrderStatus.PENDING_ACCEPT,
                    pay_status=PayStatus.PAID,
                    paid_at=now,
                    dispatched_at=now,
                ),
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


def _normalize(detail: str) -> str:
    """把消息里的 order_no 抹成占位符，用来比「结构」是否一致。"""
    head, _, _ = detail.partition("order_no=")
    return head + "order_no=<no>"


# ---------------------------------------------------------------------
# 1. 开工 -> IN_SERVICE
# ---------------------------------------------------------------------


@pytest.mark.integration
async def test_start_service_succeeds(db, seeded) -> None:
    """开工成功：订单转为「服务中」，留痕一条（MASTER）。"""
    maker = _maker(db)
    async with maker() as session:
        order = await start_service(
            session, current=_my_master(), order_no=ACCEPTED_MY_ORDER_NO
        )
    assert order.status == OrderStatus.IN_SERVICE
    assert order.order_no == ACCEPTED_MY_ORDER_NO

    stored = await _order_of(db, ACCEPTED_MY_ORDER_ID)
    assert stored.status == OrderStatus.IN_SERVICE
    # 归属不变
    assert stored.master_id == MY_MASTER_ID
    assert stored.provider_id == MY_PROVIDER_ID
    # 开工不写完成时间
    assert stored.completed_at is None

    logs = await _logs_of(db, ACCEPTED_MY_ORDER_ID)
    assert len(logs) == 1
    assert logs[0].from_status == OrderStatus.ACCEPTED
    assert logs[0].to_status == OrderStatus.IN_SERVICE
    assert logs[0].operator_type == OperatorType.MASTER
    assert logs[0].operator_id == MY_MASTER_USER_ID


@pytest.mark.integration
async def test_start_service_on_other_masters_order_returns_404(db, seeded) -> None:
    """开工别人的单 -> 404，状态未变，也没有留痕。"""
    maker = _maker(db)
    async with maker() as session:
        with pytest.raises(OrderNotFoundError):
            await start_service(
                session, current=_other_master(), order_no=ACCEPTED_MY_ORDER_NO
            )

    stored = await _order_of(db, ACCEPTED_MY_ORDER_ID)
    assert stored.status == OrderStatus.ACCEPTED
    assert stored.master_id == MY_MASTER_ID
    assert await _logs_of(db, ACCEPTED_MY_ORDER_ID) == []


@pytest.mark.integration
async def test_start_service_on_wrong_status_returns_404(db, seeded) -> None:
    """订单还没接单就想开工 -> 404，状态未变。"""
    maker = _maker(db)
    async with maker() as session:
        with pytest.raises(OrderNotFoundError):
            await start_service(
                session, current=_my_master(), order_no=WRONG_STATE_ORDER_NO
            )

    stored = await _order_of(db, WRONG_STATE_ORDER_ID)
    assert stored.status == OrderStatus.PENDING_ACCEPT
    assert await _logs_of(db, WRONG_STATE_ORDER_ID) == []


@pytest.mark.integration
async def test_start_service_without_master_identity_is_forbidden(db, seeded) -> None:
    """角色是 MASTER 但 master 表里没有身份 -> 403，订单没被动过。"""
    maker = _maker(db)
    current = CurrentUser(
        user_id=NO_MASTER_USER_ID, role=UserRole.MASTER, provider_id=None
    )
    async with maker() as session:
        with pytest.raises(ServiceFlowForbiddenError):
            await start_service(session, current=current, order_no=ACCEPTED_MY_ORDER_NO)

    stored = await _order_of(db, ACCEPTED_MY_ORDER_ID)
    assert stored.status == OrderStatus.ACCEPTED
    assert await _logs_of(db, ACCEPTED_MY_ORDER_ID) == []


# ---------------------------------------------------------------------
# 2. 完工 -> PENDING_CONFIRM
# ---------------------------------------------------------------------


@pytest.mark.integration
async def test_finish_service_succeeds(db, seeded) -> None:
    """完工成功：订单转为「待确认」，留痕一条（MASTER）。"""
    maker = _maker(db)
    async with maker() as session:
        order = await finish_service(
            session, current=_my_master(), order_no=IN_SERVICE_MY_ORDER_NO
        )
    assert order.status == OrderStatus.PENDING_CONFIRM

    stored = await _order_of(db, IN_SERVICE_MY_ORDER_ID)
    assert stored.status == OrderStatus.PENDING_CONFIRM
    assert stored.master_id == MY_MASTER_ID
    # 完工不等于完成：completed_at 要等客户确认
    assert stored.completed_at is None

    logs = await _logs_of(db, IN_SERVICE_MY_ORDER_ID)
    assert len(logs) == 1
    assert logs[0].from_status == OrderStatus.IN_SERVICE
    assert logs[0].to_status == OrderStatus.PENDING_CONFIRM
    assert logs[0].operator_type == OperatorType.MASTER


@pytest.mark.integration
async def test_finish_service_on_other_masters_order_returns_404(db, seeded) -> None:
    """完工别人的单 -> 404，状态未变，也没有留痕。"""
    maker = _maker(db)
    async with maker() as session:
        with pytest.raises(OrderNotFoundError):
            await finish_service(
                session, current=_my_master(), order_no=IN_SERVICE_OTHER_ORDER_NO
            )

    stored = await _order_of(db, IN_SERVICE_OTHER_ORDER_ID)
    assert stored.status == OrderStatus.IN_SERVICE
    assert stored.master_id == OTHER_MASTER_ID
    assert await _logs_of(db, IN_SERVICE_OTHER_ORDER_ID) == []


# ---------------------------------------------------------------------
# 3. 客户确认 -> COMPLETED
# ---------------------------------------------------------------------


@pytest.mark.integration
async def test_confirm_complete_succeeds(db, seeded) -> None:
    """客户确认成功：订单转为「已完成」，写 completed_at，留痕一条（USER）。"""
    maker = _maker(db)
    async with maker() as session:
        order = await confirm_complete(
            session, current=_customer(), order_no=PENDING_CONFIRM_MY_ORDER_NO
        )
    assert order.status == OrderStatus.COMPLETED
    assert order.completed_at is not None

    stored = await _order_of(db, PENDING_CONFIRM_MY_ORDER_ID)
    assert stored.status == OrderStatus.COMPLETED
    assert stored.completed_at is not None

    logs = await _logs_of(db, PENDING_CONFIRM_MY_ORDER_ID)
    assert len(logs) == 1
    assert logs[0].from_status == OrderStatus.PENDING_CONFIRM
    assert logs[0].to_status == OrderStatus.COMPLETED
    # 确认是客户动作，操作方类型是 USER 不是 MASTER
    assert logs[0].operator_type == OperatorType.USER
    assert logs[0].operator_id == CUSTOMER_USER_ID


@pytest.mark.integration
async def test_confirm_complete_on_other_customers_order_returns_404(db, seeded) -> None:
    """确认别人的单 -> 404，状态未变，也没有留痕。"""
    maker = _maker(db)
    async with maker() as session:
        with pytest.raises(OrderNotFoundError):
            await confirm_complete(
                session, current=_customer(), order_no=PENDING_CONFIRM_OTHER_ORDER_NO
            )

    stored = await _order_of(db, PENDING_CONFIRM_OTHER_ORDER_ID)
    assert stored.status == OrderStatus.PENDING_CONFIRM
    assert stored.completed_at is None
    assert await _logs_of(db, PENDING_CONFIRM_OTHER_ORDER_ID) == []


@pytest.mark.integration
async def test_confirm_complete_on_missing_order_returns_404(db, seeded) -> None:
    """确认一个根本不存在的订单 -> 404（与「不是我的」同构）。"""
    maker = _maker(db)
    async with maker() as session:
        with pytest.raises(OrderNotFoundError):
            await confirm_complete(
                session, current=_customer(), order_no=MISSING_ORDER_NO
            )


@pytest.mark.integration
async def test_all_failures_return_the_same_detail(db, seeded) -> None:
    """三种动作的失败响应结构完全一致（不暴露存在性）。

    失败原因有四种：订单不存在 / 不是我的 / 状态不对 / 等锁期间被改走又改回。
    对调用方是同一件事，响应里不能有任何差异。
    """
    maker = _maker(db)
    details: list[str] = []

    async def _capture(coro) -> None:
        async with maker() as session:
            with pytest.raises(OrderNotFoundError) as excinfo:
                await coro(session)
            details.append(str(excinfo.value))

    # 别人的单
    await _capture(
        lambda s: start_service(s, current=_my_master(), order_no=ACCEPTED_OTHER_ORDER_NO)
    )
    await _capture(
        lambda s: finish_service(s, current=_my_master(), order_no=IN_SERVICE_OTHER_ORDER_NO)
    )
    await _capture(
        lambda s: confirm_complete(
            s, current=_customer(), order_no=PENDING_CONFIRM_OTHER_ORDER_NO
        )
    )
    # 状态不对
    await _capture(
        lambda s: start_service(s, current=_my_master(), order_no=WRONG_STATE_ORDER_NO)
    )
    # 订单不存在
    await _capture(
        lambda s: confirm_complete(s, current=_customer(), order_no=MISSING_ORDER_NO)
    )

    normalized = {_normalize(detail) for detail in details}
    assert len(normalized) == 1, details
    assert normalized.pop() == "订单不存在：order_no=<no>"


# ---------------------------------------------------------------------
# 4. 全链路：开工 -> 完工 -> 确认
# ---------------------------------------------------------------------


@pytest.mark.integration
async def test_full_chain_start_finish_confirm(db, seeded) -> None:
    """一路走完：已接单 -> 服务中 -> 待确认 -> 已完成，三条留痕。"""
    maker = _maker(db)

    async with maker() as session:
        await start_service(
            session, current=_my_master(), order_no=ACCEPTED_MY_ORDER_NO
        )
    async with maker() as session:
        await finish_service(
            session, current=_my_master(), order_no=ACCEPTED_MY_ORDER_NO
        )
    async with maker() as session:
        await confirm_complete(
            session, current=_customer(), order_no=ACCEPTED_MY_ORDER_NO
        )

    stored = await _order_of(db, ACCEPTED_MY_ORDER_ID)
    assert stored.status == OrderStatus.COMPLETED
    assert stored.completed_at is not None

    logs = await _logs_of(db, ACCEPTED_MY_ORDER_ID)
    assert [log.to_status for log in logs] == [
        OrderStatus.IN_SERVICE,
        OrderStatus.PENDING_CONFIRM,
        OrderStatus.COMPLETED,
    ]
    assert [log.operator_type for log in logs] == [
        OperatorType.MASTER,
        OperatorType.MASTER,
        OperatorType.USER,
    ]


@pytest.mark.integration
async def test_confirm_complete_after_finished_twice_returns_404(db, seeded) -> None:
    """同一笔订单确认两次：第二次 404，不会写出第二条完成留痕。"""
    maker = _maker(db)
    async with maker() as session:
        await confirm_complete(
            session, current=_customer(), order_no=PENDING_CONFIRM_MY_ORDER_NO
        )
    async with maker() as session:
        with pytest.raises(OrderNotFoundError):
            await confirm_complete(
                session, current=_customer(), order_no=PENDING_CONFIRM_MY_ORDER_NO
            )

    assert len(await _logs_of(db, PENDING_CONFIRM_MY_ORDER_ID)) == 1


# ---------------------------------------------------------------------
# 5. 并发推进同一笔 -> 成功 1 个，失败 1 个，留痕只有 1 条
# ---------------------------------------------------------------------


@pytest.mark.integration
async def test_concurrent_start_service_only_one_wins(db, seeded) -> None:
    """同一个师傅同时开工：只有一个成功，留痕只有一条。

    条件 UPDATE 下，后到的那一方等前一方提交后重新求值谓词，
    发现订单已经不是「已接单」，于是改 0 行、按「订单不存在」处理（404）。
    """
    rendezvous = Rendezvous()
    maker = _maker(db)

    async def _start() -> str:
        async with maker() as raw_session:
            session = RendezvousSession(raw_session, rendezvous)
            try:
                await start_service(
                    session, current=_my_master(), order_no=ACCEPTED_MY_ORDER_NO
                )
                return "ok"
            except Exception as exc:  # noqa: BLE001 - 只取异常类型名做断言
                return type(exc).__name__

    results = await asyncio.gather(_start(), _start())

    assert sorted(results) == ["OrderNotFoundError", "ok"], results

    stored = await _order_of(db, ACCEPTED_MY_ORDER_ID)
    assert stored.status == OrderStatus.IN_SERVICE
    assert stored.master_id == MY_MASTER_ID

    # 留痕只有一条：没有丢更新，也没有写出两条日志
    logs = await _logs_of(db, ACCEPTED_MY_ORDER_ID)
    assert len(logs) == 1
    assert logs[0].to_status == OrderStatus.IN_SERVICE


@pytest.mark.integration
async def test_concurrent_finish_service_only_one_wins(db, seeded) -> None:
    """同一个师傅同时完工：只有一个成功，留痕只有一条。"""
    rendezvous = Rendezvous()
    maker = _maker(db)

    async def _finish() -> str:
        async with maker() as raw_session:
            session = RendezvousSession(raw_session, rendezvous)
            try:
                await finish_service(
                    session, current=_my_master(), order_no=IN_SERVICE_MY_ORDER_NO
                )
                return "ok"
            except Exception as exc:  # noqa: BLE001 - 只取异常类型名做断言
                return type(exc).__name__

    results = await asyncio.gather(_finish(), _finish())

    assert sorted(results) == ["OrderNotFoundError", "ok"], results

    stored = await _order_of(db, IN_SERVICE_MY_ORDER_ID)
    assert stored.status == OrderStatus.PENDING_CONFIRM
    assert len(await _logs_of(db, IN_SERVICE_MY_ORDER_ID)) == 1


@pytest.mark.integration
async def test_concurrent_confirm_complete_only_one_wins(db, seeded) -> None:
    """同一个客户同时确认：只有一个成功，留痕只有一条。"""
    rendezvous = Rendezvous()
    maker = _maker(db)

    async def _confirm() -> str:
        async with maker() as raw_session:
            session = RendezvousSession(raw_session, rendezvous)
            try:
                await confirm_complete(
                    session, current=_customer(), order_no=PENDING_CONFIRM_MY_ORDER_NO
                )
                return "ok"
            except Exception as exc:  # noqa: BLE001 - 只取异常类型名做断言
                return type(exc).__name__

    results = await asyncio.gather(_confirm(), _confirm())

    assert sorted(results) == ["OrderNotFoundError", "ok"], results

    stored = await _order_of(db, PENDING_CONFIRM_MY_ORDER_ID)
    assert stored.status == OrderStatus.COMPLETED
    assert len(await _logs_of(db, PENDING_CONFIRM_MY_ORDER_ID)) == 1
