"""派单 service / 接口的测试。

分两类：

- **单元测试**（不碰数据库）：请求体字段集合、service 的签名边界
  （provider_id 传不进来）、角色到操作方类型的映射；
- **集成测试**（需要真实 PostgreSQL）：真的走 HTTP -> service -> 数据库，
  验证派单成功、跨商派单、派别家师傅、重复派单、状态流转留痕、
  以及「不暴露存在性」。

集成测试用的数据库是 TEST_DATABASE_URL 指向的独立测试库
（集成 fixture 每次 drop_all + create_all，绝不碰开发库）。
"""
from __future__ import annotations

import asyncio
import inspect
import os
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.services.dispatch as dispatch_module
from app.core.auth import CurrentUser, create_access_token
from app.core.database import get_session
from app.domain.order_state import OrderTransitionError
from app.domain.order_state import assert_transition as real_assert_transition
from app.main import app
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
from app.schemas.dispatch import DispatchRequest, DispatchResult
from app.services.dispatch import dispatch_order

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

# ---------------------------------------------------------------------
# 种子数据里的 id
# ---------------------------------------------------------------------

# 服务商
MY_PROVIDER_ID = 1
# 别家服务商。这个数字故意不等于任何订单 id / 师傅 id，
# 这样断言「响应里没泄露归属」时不会和 id 撞车。
OTHER_PROVIDER_ID = 7

# 师傅
MY_MASTER_ID = 1
OTHER_MASTER_ID = 8

# 订单
OPEN_ORDER_ID = 1  # 待派单，谁都能接
FOREIGN_ORDER_ID = 2  # 已经派给别家
DISPATCHED_ORDER_ID = 3  # 已经派给本商师傅（状态 PENDING_ACCEPT）
UNPAID_ORDER_ID = 4  # 还没支付（状态 PENDING_PAY）
ASSIGNED_ORDER_ID = 5  # 归属已写入但状态还没推进（数据不一致的防御用例）

# 账号
CUSTOMER_USER_ID = 1
MY_ADMIN_USER_ID = 2
MY_STAFF_USER_ID = 3
OTHER_ADMIN_USER_ID = 4
MY_MASTER_USER_ID = 5
OTHER_MASTER_USER_ID = 6

# 不存在的 id
MISSING_ORDER_ID = 999
MISSING_MASTER_ID = 999

BASE_PRICE = Decimal("100.00")


def _url(order_id: int) -> str:
    return "/api/v1/orders/{}/dispatch".format(order_id)


def _auth_header(user_id: int, role: UserRole, provider_id: int | None) -> dict[str, str]:
    token = create_access_token(user_id, role, provider_id)
    return {"Authorization": "Bearer {}".format(token)}


def _my_admin_header() -> dict[str, str]:
    return _auth_header(MY_ADMIN_USER_ID, UserRole.PROVIDER_ADMIN, MY_PROVIDER_ID)


def _my_staff_header() -> dict[str, str]:
    return _auth_header(MY_STAFF_USER_ID, UserRole.PROVIDER_STAFF, MY_PROVIDER_ID)


def _other_admin_header() -> dict[str, str]:
    return _auth_header(OTHER_ADMIN_USER_ID, UserRole.PROVIDER_ADMIN, OTHER_PROVIDER_ID)


# =====================================================================
# 单元测试：接口契约与 service 边界
# =====================================================================


def test_dispatch_request_field_set_is_exactly_one() -> None:
    """请求体只有一个字段：master_id。

    用集合相等而不是「包含」：多一个字段（比如 provider_id）直接失败。
    """
    assert set(DispatchRequest.model_fields) == {"master_id"}


def test_dispatch_request_has_no_provider_id_field() -> None:
    """请求体里不得出现 provider_id。

    服务商归属只能来自 token，客户端自报一个就等于自选租户（R1）。
    """
    assert "provider_id" not in DispatchRequest.model_fields


def test_dispatch_request_rejects_provider_id() -> None:
    """带 provider_id 发请求 -> 校验失败（不是静默忽略）。"""
    with pytest.raises(Exception):
        DispatchRequest(master_id=1, provider_id=OTHER_PROVIDER_ID)


def test_dispatch_result_field_set_is_exactly_three() -> None:
    """响应恰好三个字段：order_no / status / master_id。"""
    assert set(DispatchResult.model_fields) == {"order_no", "status", "master_id"}


def test_dispatch_service_signature_takes_no_provider_id() -> None:
    """service 的签名里没有 provider_id 参数——不是约定别传，是传不进来。

    这条是「provider_id 只从 CurrentUser 取」的结构性保证：
    以后谁想加这个参数，测试先红。
    """
    parameters = inspect.signature(dispatch_order).parameters
    assert "provider_id" not in parameters
    assert "current_user" in parameters


def test_operator_type_mapping_only_covers_provider_roles() -> None:
    """只有服务商侧角色能映射成操作方类型。

    映射表现在住在 ``app.services.provider_scope``（派单与师傅管理共用一份，
    见那里模块头的说明），这里盯的仍是「只覆盖服务商侧角色」这条不变式。
    """
    from app.services.provider_scope import operator_type_for_provider_role

    assert (
        operator_type_for_provider_role(UserRole.PROVIDER_ADMIN)
        is OperatorType.PROVIDER_ADMIN
    )
    assert (
        operator_type_for_provider_role(UserRole.PROVIDER_STAFF)
        is OperatorType.PROVIDER_STAFF
    )
    # 平台角色与普通用户都不在服务商侧映射表里
    assert operator_type_for_provider_role(UserRole.PLATFORM_ADMIN) is None
    assert operator_type_for_provider_role(UserRole.USER) is None
    assert operator_type_for_provider_role(UserRole.MASTER) is None


def test_operator_type_for_rejects_non_provider_role() -> None:
    """非服务商侧角色调 _operator_type_for -> DispatchForbiddenError。"""
    from app.services.errors import DispatchForbiddenError

    with pytest.raises(DispatchForbiddenError):
        dispatch_module._operator_type_for(UserRole.PLATFORM_ADMIN)


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
    """种两个服务商、六个账号、两个师傅、四笔订单。

    模型层没有 relationship，SQLAlchemy 的 flush 顺序按 mapper 类名字母序
    （不是外键依赖序），所以这里按依赖顺序逐个 flush，避免外键违例。
    """
    maker = async_sessionmaker(db, class_=AsyncSession, expire_on_commit=False)
    tomorrow = date.today() + timedelta(days=1)
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
                # C 端下单用户
                User(id=CUSTOMER_USER_ID, phone="13900000001", role=UserRole.USER),
                # 本商的管理员 / 员工
                User(
                    id=MY_ADMIN_USER_ID,
                    phone="13900000002",
                    role=UserRole.PROVIDER_ADMIN,
                    provider_id=MY_PROVIDER_ID,
                ),
                User(
                    id=MY_STAFF_USER_ID,
                    phone="13900000003",
                    role=UserRole.PROVIDER_STAFF,
                    provider_id=MY_PROVIDER_ID,
                ),
                # 别家的管理员
                User(
                    id=OTHER_ADMIN_USER_ID,
                    phone="13900000004",
                    role=UserRole.PROVIDER_ADMIN,
                    provider_id=OTHER_PROVIDER_ID,
                ),
                # 师傅账号：师傅的归属权威来源是 master 表，
                # 所以 user.provider_id 必须为空（数据库 CHECK 约束强制）
                User(id=MY_MASTER_USER_ID, phone="13900000005", role=UserRole.MASTER),
                User(
                    id=OTHER_MASTER_USER_ID, phone="13900000006", role=UserRole.MASTER
                ),
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
                id=4,
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
                id=3,
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
                # 待派单：还没写归属，谁都能接
                Order(
                    id=OPEN_ORDER_ID,
                    order_no="OTO20260101000001",
                    user_id=CUSTOMER_USER_ID,
                    provider_id=None,
                    master_id=None,
                    address_id=4,
                    item_id=2,
                    slot_id=3,
                    amount=BASE_PRICE,
                    status=OrderStatus.PENDING_DISPATCH,
                    pay_status=PayStatus.PAID,
                    paid_at=now,
                ),
                # 已经派给别家
                Order(
                    id=FOREIGN_ORDER_ID,
                    order_no="OTO20260101000002",
                    user_id=CUSTOMER_USER_ID,
                    provider_id=OTHER_PROVIDER_ID,
                    master_id=OTHER_MASTER_ID,
                    address_id=4,
                    item_id=2,
                    slot_id=3,
                    amount=BASE_PRICE,
                    status=OrderStatus.PENDING_ACCEPT,
                    pay_status=PayStatus.PAID,
                    paid_at=now,
                    dispatched_at=now,
                ),
                # 已经派给本商师傅
                Order(
                    id=DISPATCHED_ORDER_ID,
                    order_no="OTO20260101000003",
                    user_id=CUSTOMER_USER_ID,
                    provider_id=MY_PROVIDER_ID,
                    master_id=MY_MASTER_ID,
                    address_id=4,
                    item_id=2,
                    slot_id=3,
                    amount=BASE_PRICE,
                    status=OrderStatus.PENDING_ACCEPT,
                    pay_status=PayStatus.PAID,
                    paid_at=now,
                    dispatched_at=now,
                ),
                # 还没支付
                Order(
                    id=UNPAID_ORDER_ID,
                    order_no="OTO20260101000004",
                    user_id=CUSTOMER_USER_ID,
                    provider_id=None,
                    master_id=None,
                    address_id=4,
                    item_id=2,
                    slot_id=3,
                    amount=BASE_PRICE,
                    status=OrderStatus.PENDING_PAY,
                    pay_status=PayStatus.UNPAID,
                ),
                # 归属已经写进去了，状态却还没推进——数据不一致的防御用例。
                # 用来单独验证「provider_id 首次写入后不可变」这条约束：
                # 状态校验在这里是放行的，挡住它的是不可变检查本身。
                Order(
                    id=ASSIGNED_ORDER_ID,
                    order_no="OTO20260101000005",
                    user_id=CUSTOMER_USER_ID,
                    provider_id=MY_PROVIDER_ID,
                    master_id=MY_MASTER_ID,
                    address_id=4,
                    item_id=2,
                    slot_id=3,
                    amount=BASE_PRICE,
                    status=OrderStatus.PENDING_DISPATCH,
                    pay_status=PayStatus.PAID,
                    paid_at=now,
                ),
            ]
        )
        await session.flush()

        # 已派单订单的原始派单留痕（用来断言「重复派单不会再写一条」）
        session.add(
            OrderStatusLog(
                order_id=DISPATCHED_ORDER_ID,
                from_status=OrderStatus.PENDING_DISPATCH,
                to_status=OrderStatus.PENDING_ACCEPT,
                operator_type=OperatorType.PROVIDER_ADMIN,
                operator_id=MY_ADMIN_USER_ID,
                reason=dispatch_module.DISPATCH_REASON,
            )
        )
        await session.flush()
        await session.commit()
    return True


@pytest.fixture
async def api_client(db):
    """接测试库的 HTTP 客户端（集成测试用）。"""
    maker = async_sessionmaker(db, class_=AsyncSession, expire_on_commit=False)

    async def override_get_session():
        async with maker() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    try:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as http_client:
            yield http_client
    finally:
        app.dependency_overrides.pop(get_session, None)


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


# ---------------------------------------------------------------------
# 1. 派本商师傅 -> 成功，状态 PENDING_ACCEPT
# ---------------------------------------------------------------------


@pytest.mark.integration
async def test_dispatch_to_own_master_succeeds(api_client, seeded, db) -> None:
    """派给本商师傅 -> 200，订单转为待接单，归属写进订单，并留痕。"""
    response = await api_client.post(
        _url(OPEN_ORDER_ID),
        json={"master_id": MY_MASTER_ID},
        headers=_my_admin_header(),
    )
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"order_no", "status", "master_id"}
    assert body["order_no"] == "OTO20260101000001"
    assert body["status"] == OrderStatus.PENDING_ACCEPT.value
    assert body["master_id"] == MY_MASTER_ID

    order = await _order_of(db, OPEN_ORDER_ID)
    assert order.status == OrderStatus.PENDING_ACCEPT
    assert order.provider_id == MY_PROVIDER_ID
    assert order.master_id == MY_MASTER_ID
    assert order.dispatched_at is not None
    # 金额是下单时的快照，派单不重新定价
    assert order.amount == BASE_PRICE

    logs = await _logs_of(db, OPEN_ORDER_ID)
    assert len(logs) == 1
    assert logs[0].from_status == OrderStatus.PENDING_DISPATCH
    assert logs[0].to_status == OrderStatus.PENDING_ACCEPT
    assert logs[0].operator_type == OperatorType.PROVIDER_ADMIN
    assert logs[0].operator_id == MY_ADMIN_USER_ID
    assert logs[0].reason == dispatch_module.DISPATCH_REASON


@pytest.mark.integration
async def test_dispatch_by_provider_staff_records_staff_as_operator(
    api_client, seeded, db
) -> None:
    """服务商员工派单 -> 留痕里的操作方类型是 PROVIDER_STAFF。"""
    response = await api_client.post(
        _url(OPEN_ORDER_ID),
        json={"master_id": MY_MASTER_ID},
        headers=_my_staff_header(),
    )
    assert response.status_code == 200

    logs = await _logs_of(db, OPEN_ORDER_ID)
    assert len(logs) == 1
    assert logs[0].operator_type == OperatorType.PROVIDER_STAFF
    assert logs[0].operator_id == MY_STAFF_USER_ID


# ---------------------------------------------------------------------
# 2. 跨商派单 -> 404，且与「订单不存在」完全一样
# ---------------------------------------------------------------------


@pytest.mark.integration
async def test_dispatch_other_provider_order_returns_404(
    api_client, seeded, db
) -> None:
    """别家的订单 -> 404，且响应与「订单不存在」逐字同构。

    消息里只有客户端自己给的 order_id，不含订单归属、订单号、状态。
    """
    foreign = await api_client.post(
        _url(FOREIGN_ORDER_ID),
        json={"master_id": MY_MASTER_ID},
        headers=_my_admin_header(),
    )
    missing = await api_client.post(
        _url(MISSING_ORDER_ID),
        json={"master_id": MY_MASTER_ID},
        headers=_my_admin_header(),
    )

    assert foreign.status_code == 404
    assert missing.status_code == 404

    # 两条消息只有 order_id 不同，而这个 id 是客户端自己给的
    assert foreign.json()["detail"] == "订单不存在：order_id={}".format(
        FOREIGN_ORDER_ID
    )
    assert missing.json()["detail"] == "订单不存在：order_id={}".format(
        MISSING_ORDER_ID
    )
    assert _normalize_order_id(foreign.json()["detail"]) == _normalize_order_id(
        missing.json()["detail"]
    )

    # 没有泄露归属信息：别家服务商 id、订单号都不出现在响应里
    assert str(OTHER_PROVIDER_ID) not in foreign.text
    assert "OTO20260101000002" not in foreign.text

    # 订单没被动过
    order = await _order_of(db, FOREIGN_ORDER_ID)
    assert order.status == OrderStatus.PENDING_ACCEPT
    assert order.provider_id == OTHER_PROVIDER_ID
    assert order.master_id == OTHER_MASTER_ID
    assert await _logs_of(db, FOREIGN_ORDER_ID) == []


def _normalize_order_id(detail: str) -> str:
    """把消息里的 order_id 抹成占位符，用来比「结构」是否一致。"""
    head, _, _ = detail.partition("order_id=")
    return head + "order_id=<id>"


# ---------------------------------------------------------------------
# 3. 派别商师傅 -> 拒绝
# ---------------------------------------------------------------------


@pytest.mark.integration
async def test_dispatch_to_other_provider_master_is_rejected(
    api_client, seeded, db
) -> None:
    """把订单派给别家师傅 -> 404，且与「师傅不存在」完全一样。"""
    foreign = await api_client.post(
        _url(OPEN_ORDER_ID),
        json={"master_id": OTHER_MASTER_ID},
        headers=_my_admin_header(),
    )
    missing = await api_client.post(
        _url(OPEN_ORDER_ID),
        json={"master_id": MISSING_MASTER_ID},
        headers=_my_admin_header(),
    )

    assert foreign.status_code == 404
    assert missing.status_code == 404
    assert foreign.json()["detail"] == "师傅不存在：master_id={}".format(
        OTHER_MASTER_ID
    )
    assert _normalize_master_id(foreign.json()["detail"]) == _normalize_master_id(
        missing.json()["detail"]
    )
    # 没有泄露归属信息
    assert str(OTHER_PROVIDER_ID) not in foreign.text

    # 订单没被动过：没有写归属、没有写师傅、状态没变、没有留痕
    order = await _order_of(db, OPEN_ORDER_ID)
    assert order.status == OrderStatus.PENDING_DISPATCH
    assert order.provider_id is None
    assert order.master_id is None
    assert order.dispatched_at is None
    assert await _logs_of(db, OPEN_ORDER_ID) == []


def _normalize_master_id(detail: str) -> str:
    """把消息里的 master_id 抹成占位符。"""
    head, _, _ = detail.partition("master_id=")
    return head + "master_id=<id>"


# ---------------------------------------------------------------------
# 4. 已派单订单再派 -> 拒绝
# ---------------------------------------------------------------------


@pytest.mark.integration
async def test_already_dispatched_order_cannot_be_dispatched_again(
    api_client, seeded, db
) -> None:
    """已派给本商师傅的订单再派 -> 409，订单原样不动，也不追加留痕。"""
    response = await api_client.post(
        _url(DISPATCHED_ORDER_ID),
        json={"master_id": MY_MASTER_ID},
        headers=_my_admin_header(),
    )
    assert response.status_code == 409

    order = await _order_of(db, DISPATCHED_ORDER_ID)
    assert order.status == OrderStatus.PENDING_ACCEPT
    assert order.provider_id == MY_PROVIDER_ID
    assert order.master_id == MY_MASTER_ID

    # 留痕还是原来那一条：重复派单没有多写
    logs = await _logs_of(db, DISPATCHED_ORDER_ID)
    assert len(logs) == 1


@pytest.mark.integration
async def test_dispatched_order_provider_id_is_immutable(
    api_client, seeded, db
) -> None:
    """订单的 provider_id 首次写入后不可变：别家不能把它抢走。

    已派单订单落到别家账号手里，同样只能得到 404，
    订单的归属保持不变。
    """
    response = await api_client.post(
        _url(DISPATCHED_ORDER_ID),
        json={"master_id": OTHER_MASTER_ID},
        headers=_other_admin_header(),
    )
    assert response.status_code == 404

    order = await _order_of(db, DISPATCHED_ORDER_ID)
    assert order.provider_id == MY_PROVIDER_ID
    assert order.master_id == MY_MASTER_ID
    assert len(await _logs_of(db, DISPATCHED_ORDER_ID)) == 1


@pytest.mark.integration
async def test_assigned_order_cannot_be_dispatched_again(
    api_client, seeded, db
) -> None:
    """归属已写入的订单不能再派：provider_id 不可变。

    这笔订单的状态还是「待派单」，所以状态校验是放行的——
    挡住它的是「provider_id 首次写入后不可变」这条约束本身。
    """
    response = await api_client.post(
        _url(ASSIGNED_ORDER_ID),
        json={"master_id": MY_MASTER_ID},
        headers=_my_admin_header(),
    )
    assert response.status_code == 409

    order = await _order_of(db, ASSIGNED_ORDER_ID)
    assert order.provider_id == MY_PROVIDER_ID
    assert order.master_id == MY_MASTER_ID
    assert order.status == OrderStatus.PENDING_DISPATCH
    assert await _logs_of(db, ASSIGNED_ORDER_ID) == []


# ---------------------------------------------------------------------
# 其余边界
# ---------------------------------------------------------------------


@pytest.mark.integration
async def test_dispatch_requires_provider_scope(api_client, seeded) -> None:
    """普通用户（没有服务商归属）派单 -> 403。"""
    response = await api_client.post(
        _url(OPEN_ORDER_ID),
        json={"master_id": MY_MASTER_ID},
        headers=_auth_header(CUSTOMER_USER_ID, UserRole.USER, None),
    )
    assert response.status_code == 403
    assert response.json() == {"detail": "Forbidden"}


@pytest.mark.integration
async def test_dispatch_rejects_provider_id_in_body(api_client, seeded, db) -> None:
    """请求体里带 provider_id -> 422，订单没被动过。"""
    response = await api_client.post(
        _url(OPEN_ORDER_ID),
        json={"master_id": MY_MASTER_ID, "provider_id": OTHER_PROVIDER_ID},
        headers=_my_admin_header(),
    )
    assert response.status_code == 422

    order = await _order_of(db, OPEN_ORDER_ID)
    assert order.status == OrderStatus.PENDING_DISPATCH
    assert order.provider_id is None
    assert await _logs_of(db, OPEN_ORDER_ID) == []


@pytest.mark.integration
async def test_dispatch_unpaid_order_returns_409(api_client, seeded, db) -> None:
    """还没支付的订单 -> 409，订单没被动过。"""
    response = await api_client.post(
        _url(UNPAID_ORDER_ID),
        json={"master_id": MY_MASTER_ID},
        headers=_my_admin_header(),
    )
    assert response.status_code == 409

    order = await _order_of(db, UNPAID_ORDER_ID)
    assert order.status == OrderStatus.PENDING_PAY
    assert order.provider_id is None
    assert await _logs_of(db, UNPAID_ORDER_ID) == []


@pytest.mark.integration
async def test_transition_goes_through_state_machine(
    api_client, seeded, monkeypatch
) -> None:
    """R4：状态流转必须经过状态机（assert_transition 被调用）。"""
    calls = []

    def _spy(from_status, to_status):
        calls.append((from_status, to_status))
        return real_assert_transition(from_status, to_status)

    monkeypatch.setattr(dispatch_module, "assert_transition", _spy)

    response = await api_client.post(
        _url(OPEN_ORDER_ID),
        json={"master_id": MY_MASTER_ID},
        headers=_my_admin_header(),
    )
    assert response.status_code == 200
    assert calls == [(OrderStatus.PENDING_DISPATCH, OrderStatus.PENDING_ACCEPT)]


@pytest.mark.integration
async def test_invalid_transition_writes_nothing(
    api_client, seeded, db, monkeypatch
) -> None:
    """变异验证：assert_transition 抛异常时，订单状态与留痕都不许被写。

    把状态机换成「一律抛异常」，service 必须原样抛出来，
    且数据库里订单状态不变、归属不变、没有状态流转日志。
    """

    def _boom(from_status, to_status):
        raise OrderTransitionError(from_status, to_status)

    monkeypatch.setattr(dispatch_module, "assert_transition", _boom)

    response = await api_client.post(
        _url(OPEN_ORDER_ID),
        json={"master_id": MY_MASTER_ID},
        headers=_my_admin_header(),
    )
    # OrderTransitionError 不在业务异常树里，原样冒泡成 500
    assert response.status_code == 500

    order = await _order_of(db, OPEN_ORDER_ID)
    assert order.status == OrderStatus.PENDING_DISPATCH
    assert order.provider_id is None
    assert order.master_id is None
    assert await _logs_of(db, OPEN_ORDER_ID) == []


# =====================================================================
# 集成测试：并发派单
# =====================================================================


class _Rendezvous:
    """一次性的会合点：两个协程都到了才一起放行。

    只等一个协程时最多等 10 秒就放行——测试宁可失败也不能挂死。
    """

    def __init__(self, parties: int = 2) -> None:
        self._parties = parties
        self._arrived = 0
        self._released = asyncio.Event()

    async def wait(self) -> None:
        self._arrived += 1
        if self._arrived >= self._parties:
            self._released.set()
        try:
            await asyncio.wait_for(self._released.wait(), timeout=10)
        except asyncio.TimeoutError:
            pass


def _is_master_select(statement) -> bool:
    """判断这条语句是不是「查 master 表」。

    按 ORM 实体判断，不能按语句文本里有没有 "master"：
    order 表有个 master_id 列，「SELECT order.id, order.master_id, ...」
    的文本里同样含 "master"，按文本判断会把查订单也当成查师傅。
    """
    if not isinstance(statement, Select):
        return False
    try:
        entity = statement.column_descriptions[0].get("entity")
    except Exception:  # noqa: BLE001 - 认不出来就当不是
        return False
    return entity is Master


class _RendezvousSession:
    """在「第一次查 master」处会合的会话包装。

    作用是把两个并发派单强制排在同一个时间窗里，好让竞态出现：
    - 读-改-写的实现下，两个协程都会先读到「还没派」（provider_id IS NULL），
      然后各自写一遍 -> 丢更新，两边都成功；
    - 条件 UPDATE 的实现下，两个协程同时改，由数据库的行锁裁决，
      只有一方能改成功。

    会话的其他方法（begin / flush / add ...）原样转发给真实会话。
    """

    def __init__(self, session, rendezvous: _Rendezvous) -> None:
        self._session = session
        self._rendezvous = rendezvous
        self._armed = True

    async def execute(self, statement, *args, **kwargs):
        if self._armed and _is_master_select(statement):
            # 每个会话只拦一次：拦第二次会把自己也卡住
            self._armed = False
            await self._rendezvous.wait()
        return await self._session.execute(statement, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._session, name)


@pytest.mark.integration
async def test_concurrent_dispatch_only_one_wins(db, seeded) -> None:
    """两个服务商同时派同一笔订单：只有一个成功，归属只属于赢家，留痕只有一条。

    条件 UPDATE 下，后到的那一方等前一方提交后重新求值谓词，
    发现订单已经被派走，于是影响 0 行、按「不是本商的订单」处理（404）。
    """
    rendezvous = _Rendezvous()
    maker = async_sessionmaker(db, class_=AsyncSession, expire_on_commit=False)

    async def _dispatch(provider_id: int, user_id: int, master_id: int) -> str:
        async with maker() as raw_session:
            session = _RendezvousSession(raw_session, rendezvous)
            current = CurrentUser(
                user_id=user_id,
                role=UserRole.PROVIDER_ADMIN,
                provider_id=provider_id,
            )
            try:
                await dispatch_order(
                    session,
                    order_id=OPEN_ORDER_ID,
                    master_id=master_id,
                    current_user=current,
                )
                return "ok"
            except Exception as exc:  # noqa: BLE001 - 只取异常类型名做断言
                return type(exc).__name__

    results = await asyncio.gather(
        _dispatch(MY_PROVIDER_ID, MY_ADMIN_USER_ID, MY_MASTER_ID),
        _dispatch(OTHER_PROVIDER_ID, OTHER_ADMIN_USER_ID, OTHER_MASTER_ID),
    )

    # 一个成功，另一个按「订单不是自己的」被拒（404 同构）
    assert sorted(results) == ["OrderNotFoundError", "ok"], results

    winner_index = results.index("ok")
    winner_provider = MY_PROVIDER_ID if winner_index == 0 else OTHER_PROVIDER_ID
    winner_master = MY_MASTER_ID if winner_index == 0 else OTHER_MASTER_ID

    order = await _order_of(db, OPEN_ORDER_ID)
    # 归属只属于赢家：没有丢更新
    assert order.provider_id == winner_provider
    assert order.master_id == winner_master
    assert order.status == OrderStatus.PENDING_ACCEPT

    # 留痕只有一条：赢家的那次
    logs = await _logs_of(db, OPEN_ORDER_ID)
    assert len(logs) == 1
    assert logs[0].from_status == OrderStatus.PENDING_DISPATCH
    assert logs[0].to_status == OrderStatus.PENDING_ACCEPT
    assert logs[0].operator_id == (
        MY_ADMIN_USER_ID if winner_index == 0 else OTHER_ADMIN_USER_ID
    )
