"""服务流转接口（开工 / 完工 / 确认完成）的测试。

分两类：

- **单元测试**（不碰数据库）：路由契约——三个动作都从路径取 order_no、
  身份只从 token 取（没有请求体）、响应字段集合固定；
- **集成测试**（需要真实 PostgreSQL）：真的走 HTTP -> service -> 数据库，
  验证开工 / 完工 / 确认三个动作、角色不对时的 403、以及
  「请求体不能注入身份」。

集成测试用的数据库是 TEST_DATABASE_URL 指向的独立测试库
（集成 fixture 每次 drop_all + create_all，绝不碰开发库）。
"""
from __future__ import annotations

import inspect
import os
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from tests.support import business_today
from app.core.auth import create_access_token
from app.core.database import get_session
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
from app.schemas.service_flow import ServiceFlowResult

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

# ---------------------------------------------------------------------
# 种子数据里的 id
# ---------------------------------------------------------------------

MY_PROVIDER_ID = 1
MY_MASTER_ID = 1  # 本商师傅
DISABLED_MASTER_ID = 2  # 本商师傅，但已停用（不让他干活）
ON_LEAVE_MASTER_ID = 3  # 本商师傅，在休假（同样不让他干活）

CUSTOMER_USER_ID = 1  # 客户（订单的主人）
MY_MASTER_USER_ID = 2  # 师傅账号（master 表里有身份）
DISABLED_MASTER_USER_ID = 3  # 已停用的师傅账号
ON_LEAVE_MASTER_USER_ID = 4  # 休假的师傅账号

ACCEPTED_ORDER_ID = 1  # 已接单 -> 可以开工
IN_SERVICE_ORDER_ID = 2  # 服务中 -> 可以完工
PENDING_CONFIRM_ORDER_ID = 3  # 待确认 -> 可以确认完成
DISABLED_MASTER_ORDER_ID = 4  # 派给已停用师傅的已接单单
ON_LEAVE_MASTER_ORDER_ID = 5  # 派给休假师傅的服务中订单

BASE_PRICE = Decimal("100.00")

ACCEPTED_ORDER_NO = "OTO20260301000001"
IN_SERVICE_ORDER_NO = "OTO20260301000002"
PENDING_CONFIRM_ORDER_NO = "OTO20260301000003"
DISABLED_MASTER_ORDER_NO = "OTO20260301000004"
ON_LEAVE_MASTER_ORDER_NO = "OTO20260301000005"
MISSING_ORDER_NO = "OTO20260301009999"


def _start_url(order_no: str) -> str:
    return "/api/v1/orders/{}/start".format(order_no)


def _finish_url(order_no: str) -> str:
    return "/api/v1/orders/{}/finish".format(order_no)


def _confirm_url(order_no: str) -> str:
    return "/api/v1/orders/{}/confirm".format(order_no)


def _auth_header(user_id: int, role: UserRole, provider_id: int | None) -> dict[str, str]:
    token = create_access_token(user_id, role, provider_id)
    return {"Authorization": "Bearer {}".format(token)}


def _my_master_header() -> dict[str, str]:
    return _auth_header(MY_MASTER_USER_ID, UserRole.MASTER, None)


def _disabled_master_header() -> dict[str, str]:
    """已停用的师傅账号。"""
    return _auth_header(DISABLED_MASTER_USER_ID, UserRole.MASTER, None)


def _on_leave_master_header() -> dict[str, str]:
    """休假的师傅账号。"""
    return _auth_header(ON_LEAVE_MASTER_USER_ID, UserRole.MASTER, None)


def _customer_header() -> dict[str, str]:
    return _auth_header(CUSTOMER_USER_ID, UserRole.USER, None)


# =====================================================================
# 单元测试：接口契约
# =====================================================================


def test_three_flow_routes_are_registered() -> None:
    """三个动作都有路由，且路径以订单号定位、是 POST。

    用 OpenAPI 文档取路径：这版 FastAPI 的 ``app.routes`` 里放的是
    ``_IncludedRouter`` 包装对象，真正的路由在它下面，展平了看。
    """
    paths = app.openapi()["paths"]
    for path in (
        "/api/v1/orders/{order_no}/start",
        "/api/v1/orders/{order_no}/finish",
        "/api/v1/orders/{order_no}/confirm",
    ):
        assert path in paths, path
        assert "post" in paths[path], path


def test_flow_endpoints_take_no_request_body() -> None:
    """三个动作**没有请求体**：订单号从路径取，身份从 token 取。

    没有请求体，就不存在「客户端在 body 里自报 user_id / master_id」
    这条路——身份只能由服务端从 token 推出来（R1）。
    """
    from app.api.v1 import orders as orders_module

    for func in (
        orders_module.start_order_service,
        orders_module.finish_order_service,
        orders_module.confirm_order_service,
    ):
        parameters = inspect.signature(func).parameters
        assert set(parameters) == {"order_no", "session", "current_user"}, func.__name__
        assert "payload" not in parameters
        assert "body" not in parameters
        assert "user_id" not in parameters
        assert "master_id" not in parameters


def test_flow_result_field_set() -> None:
    """响应字段集合固定：订单号、状态、完工时间。"""
    assert set(ServiceFlowResult.model_fields) == {"order_no", "status", "completed_at"}


def test_flow_result_rejects_extra_fields() -> None:
    """响应里不塞多余字段。"""
    with pytest.raises(Exception):
        ServiceFlowResult(
            order_no=ACCEPTED_ORDER_NO,
            status=OrderStatus.IN_SERVICE,
            completed_at=None,
            master_id=MY_MASTER_ID,
        )


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
    """种一个服务商、两个账号、一个师傅、三笔订单。

    模型层没有 relationship，SQLAlchemy 的 flush 顺序按 mapper 类名字母序
    （不是外键依赖序），所以这里按依赖顺序逐个 flush，避免外键违例。
    """
    maker = async_sessionmaker(db, class_=AsyncSession, expire_on_commit=False)
    tomorrow = business_today() + timedelta(days=1)
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
                # 师傅账号：师傅的归属权威来源是 master 表，
                # 所以 user.provider_id 必须为空（数据库 CHECK 约束强制）
                User(id=MY_MASTER_USER_ID, phone="13900000002", role=UserRole.MASTER),
                # 不在岗的师傅账号（停用 / 休假）
                User(
                    id=DISABLED_MASTER_USER_ID,
                    phone="13900000003",
                    role=UserRole.MASTER,
                ),
                User(
                    id=ON_LEAVE_MASTER_USER_ID,
                    phone="13900000004",
                    role=UserRole.MASTER,
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
                # 不在岗的师傅：接不了单，也开不了工 / 完不了工
                Master(
                    id=DISABLED_MASTER_ID,
                    provider_id=MY_PROVIDER_ID,
                    user_id=DISABLED_MASTER_USER_ID,
                    real_name="停用师傅",
                    status=MasterStatus.DISABLED,
                ),
                Master(
                    id=ON_LEAVE_MASTER_ID,
                    provider_id=MY_PROVIDER_ID,
                    user_id=ON_LEAVE_MASTER_USER_ID,
                    real_name="休假师傅",
                    status=MasterStatus.ON_LEAVE,
                ),
            ]
        )
        await session.flush()

        now = datetime.now(timezone.utc)
        session.add_all(
            [
                # 已接单 -> 可以开工
                Order(
                    id=ACCEPTED_ORDER_ID,
                    order_no=ACCEPTED_ORDER_NO,
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
                # 服务中 -> 可以完工
                Order(
                    id=IN_SERVICE_ORDER_ID,
                    order_no=IN_SERVICE_ORDER_NO,
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
                # 待确认 -> 可以确认完成。
                # 承接师傅是**已停用**的：确认权在客户手上，
                # 师傅在不在岗跟客户能不能确认没关系（见下面那条测试）
                Order(
                    id=PENDING_CONFIRM_ORDER_ID,
                    order_no=PENDING_CONFIRM_ORDER_NO,
                    user_id=CUSTOMER_USER_ID,
                    provider_id=MY_PROVIDER_ID,
                    master_id=DISABLED_MASTER_ID,
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
                # 派给已停用师傅的已接单单：他想开工 -> 409
                Order(
                    id=DISABLED_MASTER_ORDER_ID,
                    order_no=DISABLED_MASTER_ORDER_NO,
                    user_id=CUSTOMER_USER_ID,
                    provider_id=MY_PROVIDER_ID,
                    master_id=DISABLED_MASTER_ID,
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
                # 派给休假师傅的服务中订单：他想完工 -> 409
                Order(
                    id=ON_LEAVE_MASTER_ORDER_ID,
                    order_no=ON_LEAVE_MASTER_ORDER_NO,
                    user_id=CUSTOMER_USER_ID,
                    provider_id=MY_PROVIDER_ID,
                    master_id=ON_LEAVE_MASTER_ID,
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
            ]
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
# 1. 开工 -> 200，订单转到「服务中」
# ---------------------------------------------------------------------


@pytest.mark.integration
async def test_start_endpoint_returns_200(api_client, seeded, db) -> None:
    """师傅开工 -> 200，订单转到「服务中」，留痕一条。"""
    response = await api_client.post(
        _start_url(ACCEPTED_ORDER_NO),
        headers=_my_master_header(),
    )
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"order_no", "status", "completed_at"}
    assert body["order_no"] == ACCEPTED_ORDER_NO
    assert body["status"] == OrderStatus.IN_SERVICE.value
    # 还没做完：完工时间为空
    assert body["completed_at"] is None

    order = await _order_of(db, ACCEPTED_ORDER_ID)
    assert order.status == OrderStatus.IN_SERVICE
    assert order.master_id == MY_MASTER_ID
    assert order.completed_at is None

    logs = await _logs_of(db, ACCEPTED_ORDER_ID)
    assert len(logs) == 1
    assert logs[0].from_status == OrderStatus.ACCEPTED
    assert logs[0].to_status == OrderStatus.IN_SERVICE
    assert logs[0].operator_type == OperatorType.MASTER
    assert logs[0].operator_id == MY_MASTER_USER_ID


# ---------------------------------------------------------------------
# 2. 完工 -> 200，订单转到「待确认」
# ---------------------------------------------------------------------


@pytest.mark.integration
async def test_finish_endpoint_returns_200(api_client, seeded, db) -> None:
    """师傅完工 -> 200，订单转到「待确认」，留痕一条。"""
    response = await api_client.post(
        _finish_url(IN_SERVICE_ORDER_NO),
        headers=_my_master_header(),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == OrderStatus.PENDING_CONFIRM.value
    assert body["completed_at"] is None

    order = await _order_of(db, IN_SERVICE_ORDER_ID)
    assert order.status == OrderStatus.PENDING_CONFIRM
    # 师傅说「做完了」不等于订单完成：完工时间还没写
    assert order.completed_at is None

    logs = await _logs_of(db, IN_SERVICE_ORDER_ID)
    assert len(logs) == 1
    assert logs[0].from_status == OrderStatus.IN_SERVICE
    assert logs[0].to_status == OrderStatus.PENDING_CONFIRM
    assert logs[0].operator_type == OperatorType.MASTER


# ---------------------------------------------------------------------
# 2.5 师傅状态：只有 ACTIVE 能开工 / 完工
# ---------------------------------------------------------------------


@pytest.mark.integration
async def test_inactive_master_cannot_start_or_finish(
    api_client, seeded, db
) -> None:
    """不在岗的师傅开工 / 完工 -> 409「师傅当前不可接单」，订单没动。

    与派单（dispatch）、接单（master_action）是同一条规则：服务商把师傅
    停用之后，他在哪一头都不该再干活。
    """
    start = await api_client.post(
        _start_url(DISABLED_MASTER_ORDER_NO),
        headers=_disabled_master_header(),
    )
    assert start.status_code == 409
    assert start.json()["detail"] == "师傅当前不可接单：master_id={}".format(
        DISABLED_MASTER_ID
    )

    finish = await api_client.post(
        _finish_url(ON_LEAVE_MASTER_ORDER_NO),
        headers=_on_leave_master_header(),
    )
    assert finish.status_code == 409
    assert finish.json()["detail"] == "师傅当前不可接单：master_id={}".format(
        ON_LEAVE_MASTER_ID
    )

    # 订单一个字节都没动，也没留痕
    disabled_order = await _order_of(db, DISABLED_MASTER_ORDER_ID)
    assert disabled_order.status == OrderStatus.ACCEPTED
    assert await _logs_of(db, DISABLED_MASTER_ORDER_ID) == []

    leave_order = await _order_of(db, ON_LEAVE_MASTER_ORDER_ID)
    assert leave_order.status == OrderStatus.IN_SERVICE
    assert await _logs_of(db, ON_LEAVE_MASTER_ORDER_ID) == []


@pytest.mark.integration
async def test_active_master_can_start_and_finish(api_client, seeded, db) -> None:
    """在岗的师傅开工 / 完工 -> 200。

    与上面那条对着看：同一个接口，区别只在师傅状态。
    没有这条对照，409 可能来自别的原因（比如订单本身的状态不对）。
    """
    start = await api_client.post(
        _start_url(ACCEPTED_ORDER_NO),
        headers=_my_master_header(),
    )
    assert start.status_code == 200
    assert start.json()["status"] == OrderStatus.IN_SERVICE.value

    finish = await api_client.post(
        _finish_url(IN_SERVICE_ORDER_NO),
        headers=_my_master_header(),
    )
    assert finish.status_code == 200
    assert finish.json()["status"] == OrderStatus.PENDING_CONFIRM.value

    assert (await _order_of(db, ACCEPTED_ORDER_ID)).status == OrderStatus.IN_SERVICE
    assert (
        await _order_of(db, IN_SERVICE_ORDER_ID)
    ).status == OrderStatus.PENDING_CONFIRM


@pytest.mark.integration
async def test_customer_can_confirm_regardless_of_master_status(
    api_client, seeded, db
) -> None:
    """客户确认完成**不查**师傅状态。

    确认权在客户手上，跟师傅在不在岗没关系：师傅被停用之后，
    客户手上那笔待确认的订单照样能确认（不然这单就卡死了）。
    """
    # 这笔单的承接师傅正是已停用的那位
    assert (await _order_of(db, PENDING_CONFIRM_ORDER_ID)).master_id == (
        DISABLED_MASTER_ID
    )

    response = await api_client.post(
        _confirm_url(PENDING_CONFIRM_ORDER_NO),
        headers=_customer_header(),
    )
    assert response.status_code == 200
    assert response.json()["status"] == OrderStatus.COMPLETED.value


# ---------------------------------------------------------------------
# 3. 确认完成 -> 200，订单转到「已完成」，写完工时间
# ---------------------------------------------------------------------


@pytest.mark.integration
async def test_confirm_endpoint_returns_200(api_client, seeded, db) -> None:
    """客户确认完成 -> 200，订单转到「已完成」，并写入完工时间。"""
    response = await api_client.post(
        _confirm_url(PENDING_CONFIRM_ORDER_NO),
        headers=_customer_header(),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == OrderStatus.COMPLETED.value
    assert body["completed_at"] is not None

    order = await _order_of(db, PENDING_CONFIRM_ORDER_ID)
    assert order.status == OrderStatus.COMPLETED
    assert order.completed_at is not None
    # 人工确认，不是自动确认
    assert order.auto_confirmed is False

    logs = await _logs_of(db, PENDING_CONFIRM_ORDER_ID)
    assert len(logs) == 1
    assert logs[0].from_status == OrderStatus.PENDING_CONFIRM
    assert logs[0].to_status == OrderStatus.COMPLETED
    assert logs[0].operator_type == OperatorType.USER
    assert logs[0].operator_id == CUSTOMER_USER_ID


# ---------------------------------------------------------------------
# 4. 角色不对 -> 403
# ---------------------------------------------------------------------


@pytest.mark.integration
async def test_start_by_non_master_returns_403(api_client, seeded, db) -> None:
    """普通用户调开工 -> 403，订单没被动过。"""
    response = await api_client.post(
        _start_url(ACCEPTED_ORDER_NO),
        headers=_customer_header(),
    )
    assert response.status_code == 403
    assert response.json() == {"detail": "当前角色不能执行师傅侧服务动作"}

    order = await _order_of(db, ACCEPTED_ORDER_ID)
    assert order.status == OrderStatus.ACCEPTED
    assert await _logs_of(db, ACCEPTED_ORDER_ID) == []


@pytest.mark.integration
async def test_confirm_by_master_returns_403(api_client, seeded, db) -> None:
    """师傅调确认完成 -> 403（确认权在客户手上）。"""
    response = await api_client.post(
        _confirm_url(PENDING_CONFIRM_ORDER_NO),
        headers=_my_master_header(),
    )
    assert response.status_code == 403

    order = await _order_of(db, PENDING_CONFIRM_ORDER_ID)
    assert order.status == OrderStatus.PENDING_CONFIRM
    assert await _logs_of(db, PENDING_CONFIRM_ORDER_ID) == []


@pytest.mark.integration
async def test_flow_endpoint_requires_authentication(api_client, seeded) -> None:
    """没带 token -> 401。"""
    response = await api_client.post(_start_url(ACCEPTED_ORDER_NO))
    assert response.status_code == 401


# ---------------------------------------------------------------------
# 5. 请求体不能注入身份
# ---------------------------------------------------------------------


@pytest.mark.integration
async def test_request_body_cannot_inject_identity(api_client, seeded, db) -> None:
    """请求体里带 user_id / master_id 不影响身份判断。

    三个动作根本没有请求体，所以 body 里的字段会被直接忽略：
    身份永远来自 token。客户在 body 里自报一个 master_id 也开不了工。
    """
    # 客户的 token + body 里自报 master_id -> 还是 403（body 给不了身份）
    customer = await api_client.post(
        _start_url(ACCEPTED_ORDER_NO),
        json={"user_id": CUSTOMER_USER_ID, "master_id": MY_MASTER_ID},
        headers=_customer_header(),
    )
    assert customer.status_code == 403

    # 师傅的 token + body 里自报 user_id -> 照常开工（body 被忽略）
    master = await api_client.post(
        _start_url(ACCEPTED_ORDER_NO),
        json={"user_id": CUSTOMER_USER_ID},
        headers=_my_master_header(),
    )
    assert master.status_code == 200
    assert master.json()["status"] == OrderStatus.IN_SERVICE.value


# ---------------------------------------------------------------------
# 6. 404 同构：不暴露订单存在性
# ---------------------------------------------------------------------


@pytest.mark.integration
async def test_unknown_order_returns_404(api_client, seeded, db) -> None:
    """订单不存在 -> 404，消息只回客户端自己给的订单号。"""
    response = await api_client.post(
        _start_url(MISSING_ORDER_NO),
        headers=_my_master_header(),
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "订单不存在：order_no={}".format(
        MISSING_ORDER_NO
    )
