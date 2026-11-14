"""师傅接单 / 拒单 service / 接口的测试。

分两类：

- **单元测试**（不碰数据库）：请求体字段集合、service 的签名边界
  （master_id 传不进来）、状态机是否被调用；
- **集成测试**（需要真实 PostgreSQL）：真的走 HTTP -> service -> 数据库，
  验证接单成功、接别人的单、拒单退回、并发接单、拒单后重新派单、
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

import app.services.master_action as master_action_module
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
from app.schemas.master_action import AcceptResult, RejectRequest, RejectResult
from app.services.master_action import accept_order, reject_order

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
MY_OTHER_MASTER_ID = 9  # 本商另一个师傅（拒单后改派给他）
MISMATCHED_MASTER_ID = 10  # 身份错乱：token 说本商，master 表说别家

# 订单
MY_ORDER_ID = 1  # 派给我的师傅，待接单
OTHER_MASTER_ORDER_ID = 2  # 派给别家师傅
NOT_DISPATCHED_ORDER_ID = 3  # 还没派单
ACCEPTED_ORDER_ID = 4  # 已经接单
UNPAID_ORDER_ID = 5  # 还没支付

# 账号
CUSTOMER_USER_ID = 1
MY_ADMIN_USER_ID = 2
OTHER_ADMIN_USER_ID = 3
MY_MASTER_USER_ID = 4
OTHER_MASTER_USER_ID = 5
MY_OTHER_MASTER_USER_ID = 6
MISMATCHED_USER_ID = 7  # 本商管理员，但 master 表把他挂在别家

BASE_PRICE = Decimal("100.00")

MY_ORDER_NO = "OTO20260101000001"
OTHER_MASTER_ORDER_NO = "OTO20260101000002"
NOT_DISPATCHED_ORDER_NO = "OTO20260101000003"
ACCEPTED_ORDER_NO = "OTO20260101000004"
UNPAID_ORDER_NO = "OTO20260101000005"
MISSING_ORDER_NO = "OTO20260101009999"


def _accept_url(order_no: str) -> str:
    return "/api/v1/orders/{}/accept".format(order_no)


def _reject_url(order_no: str) -> str:
    return "/api/v1/orders/{}/reject".format(order_no)


def _dispatch_url(order_id: int) -> str:
    return "/api/v1/orders/{}/dispatch".format(order_id)


def _auth_header(user_id: int, role: UserRole, provider_id: int | None) -> dict[str, str]:
    token = create_access_token(user_id, role, provider_id)
    return {"Authorization": "Bearer {}".format(token)}


def _my_master_header() -> dict[str, str]:
    return _auth_header(MY_MASTER_USER_ID, UserRole.MASTER, None)


def _other_master_header() -> dict[str, str]:
    return _auth_header(OTHER_MASTER_USER_ID, UserRole.MASTER, None)


def _my_admin_header() -> dict[str, str]:
    return _auth_header(MY_ADMIN_USER_ID, UserRole.PROVIDER_ADMIN, MY_PROVIDER_ID)


# =====================================================================
# 单元测试：接口契约与 service 边界
# =====================================================================


def test_accept_service_signature_takes_no_master_id() -> None:
    """接单 service 的签名里没有 master_id / order_id 参数。

    师傅身份只能从 CurrentUser 查 master 表得到，订单只能按 order_no 定位。
    这是「身份不从入参取」的结构性保证：以后谁想加这个参数，测试先红。
    """
    parameters = inspect.signature(accept_order).parameters
    assert "master_id" not in parameters
    assert "order_id" not in parameters
    assert "order_no" in parameters
    assert "current_user" in parameters


def test_reject_service_signature_takes_no_master_id() -> None:
    """拒单 service 的签名里同样没有 master_id。"""
    parameters = inspect.signature(reject_order).parameters
    assert "master_id" not in parameters
    assert "order_id" not in parameters
    assert "order_no" in parameters
    assert "current_user" in parameters


def test_reject_service_requires_reason() -> None:
    """拒单必须带 reason；接单不带。"""
    assert "reason" in inspect.signature(reject_order).parameters
    assert "reason" not in inspect.signature(accept_order).parameters


def test_reject_request_field_set_is_exactly_one() -> None:
    """拒单请求体只有一个字段：reason。"""
    assert set(RejectRequest.model_fields) == {"reason"}


def test_reject_request_rejects_extra_fields() -> None:
    """请求体里带 master_id / provider_id -> 校验失败（不是静默忽略）。

    师傅身份只能由服务端从 token 查出来，客户端自报一个就是自选身份（R1）。
    """
    with pytest.raises(Exception):
        RejectRequest(reason="临时有事", master_id=OTHER_MASTER_ID)
    with pytest.raises(Exception):
        RejectRequest(reason="临时有事", provider_id=OTHER_PROVIDER_ID)


def test_reject_request_rejects_empty_reason() -> None:
    """空 reason 不许提交。"""
    with pytest.raises(Exception):
        RejectRequest(reason="")


def test_result_field_sets() -> None:
    """响应字段集合固定。"""
    assert set(AcceptResult.model_fields) == {"order_no", "status", "master_id"}
    assert set(RejectResult.model_fields) == {"order_no", "status", "master_id"}


def test_accept_reason_constant() -> None:
    """接单留痕用的原因常量固定。"""
    assert master_action_module.ACCEPT_REASON == "师傅接单"


def test_operator_type_is_master() -> None:
    """接单/拒单都是师傅侧动作，操作方类型固定是 MASTER。

    与 dispatch 不同：dispatch 要按角色区分管理员/员工，所以有角色映射表；
    接单/拒单只有师傅一种操作方，没有映射表可写。
    """
    source = inspect.getsource(master_action_module)
    assert "OperatorType.MASTER" in source
    assert "OperatorType.PROVIDER_ADMIN" not in source
    assert "OperatorType.PROVIDER_STAFF" not in source


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
    """种两个服务商、七个账号、四个师傅、五笔订单。

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
                User(id=CUSTOMER_USER_ID, phone="13900000001", role=UserRole.USER),
                User(
                    id=MY_ADMIN_USER_ID,
                    phone="13900000002",
                    role=UserRole.PROVIDER_ADMIN,
                    provider_id=MY_PROVIDER_ID,
                ),
                User(
                    id=OTHER_ADMIN_USER_ID,
                    phone="13900000003",
                    role=UserRole.PROVIDER_ADMIN,
                    provider_id=OTHER_PROVIDER_ID,
                ),
                # 师傅账号：师傅的归属权威来源是 master 表，
                # 所以 user.provider_id 必须为空（数据库 CHECK 约束强制）
                User(id=MY_MASTER_USER_ID, phone="13900000004", role=UserRole.MASTER),
                User(
                    id=OTHER_MASTER_USER_ID, phone="13900000005", role=UserRole.MASTER
                ),
                User(
                    id=MY_OTHER_MASTER_USER_ID,
                    phone="13900000006",
                    role=UserRole.MASTER,
                ),
                # 身份错乱的账号：token 里是本商管理员，master 表却挂在别家
                User(
                    id=MISMATCHED_USER_ID,
                    phone="13900000007",
                    role=UserRole.PROVIDER_ADMIN,
                    provider_id=MY_PROVIDER_ID,
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
                Master(
                    id=MY_OTHER_MASTER_ID,
                    provider_id=MY_PROVIDER_ID,
                    user_id=MY_OTHER_MASTER_USER_ID,
                    real_name="王师傅",
                    status=MasterStatus.ACTIVE,
                ),
                Master(
                    id=MISMATCHED_MASTER_ID,
                    provider_id=OTHER_PROVIDER_ID,
                    user_id=MISMATCHED_USER_ID,
                    real_name="赵师傅",
                    status=MasterStatus.ACTIVE,
                ),
            ]
        )
        await session.flush()

        now = datetime.now(timezone.utc)
        session.add_all(
            [
                # 派给我的师傅，等我接单
                Order(
                    id=MY_ORDER_ID,
                    order_no=MY_ORDER_NO,
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
                # 派给别家师傅
                Order(
                    id=OTHER_MASTER_ORDER_ID,
                    order_no=OTHER_MASTER_ORDER_NO,
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
                # 还没派单
                Order(
                    id=NOT_DISPATCHED_ORDER_ID,
                    order_no=NOT_DISPATCHED_ORDER_NO,
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
                # 已经接单
                Order(
                    id=ACCEPTED_ORDER_ID,
                    order_no=ACCEPTED_ORDER_NO,
                    user_id=CUSTOMER_USER_ID,
                    provider_id=MY_PROVIDER_ID,
                    master_id=MY_MASTER_ID,
                    address_id=4,
                    item_id=2,
                    slot_id=3,
                    amount=BASE_PRICE,
                    status=OrderStatus.ACCEPTED,
                    pay_status=PayStatus.PAID,
                    paid_at=now,
                    dispatched_at=now,
                    accepted_at=now,
                ),
                # 还没支付
                Order(
                    id=UNPAID_ORDER_ID,
                    order_no=UNPAID_ORDER_NO,
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


def _normalize_order_no(detail: str) -> str:
    """把消息里的 order_no 抹成占位符，用来比「结构」是否一致。"""
    head, _, _ = detail.partition("order_no=")
    return head + "order_no=<no>"


# ---------------------------------------------------------------------
# 1. 接自己的单 -> ACCEPTED
# ---------------------------------------------------------------------


@pytest.mark.integration
async def test_accept_own_order_succeeds(api_client, seeded, db) -> None:
    """接下派给我的订单 -> 200，订单转为「已接单」，并留痕。"""
    response = await api_client.post(
        _accept_url(MY_ORDER_NO),
        headers=_my_master_header(),
    )
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"order_no", "status", "master_id"}
    assert body["order_no"] == MY_ORDER_NO
    assert body["status"] == OrderStatus.ACCEPTED.value
    assert body["master_id"] == MY_MASTER_ID

    order = await _order_of(db, MY_ORDER_ID)
    assert order.status == OrderStatus.ACCEPTED
    assert order.accepted_at is not None
    # 接单不改归属
    assert order.provider_id == MY_PROVIDER_ID
    assert order.master_id == MY_MASTER_ID

    logs = await _logs_of(db, MY_ORDER_ID)
    assert len(logs) == 1
    assert logs[0].from_status == OrderStatus.PENDING_ACCEPT
    assert logs[0].to_status == OrderStatus.ACCEPTED
    assert logs[0].operator_type == OperatorType.MASTER
    assert logs[0].operator_id == MY_MASTER_USER_ID
    assert logs[0].reason == master_action_module.ACCEPT_REASON


# ---------------------------------------------------------------------
# 2. 接别人的单 -> 404 同构，状态未变
# ---------------------------------------------------------------------


@pytest.mark.integration
async def test_accept_other_masters_order_returns_404(api_client, seeded, db) -> None:
    """派给别家师傅的订单 -> 404，且与「订单不存在」逐字同构。

    消息里只有客户端自己给的 order_no，不含订单归属、师傅、状态。
    """
    foreign = await api_client.post(
        _accept_url(OTHER_MASTER_ORDER_NO),
        headers=_my_master_header(),
    )
    missing = await api_client.post(
        _accept_url(MISSING_ORDER_NO),
        headers=_my_master_header(),
    )

    assert foreign.status_code == 404
    assert missing.status_code == 404
    assert foreign.json()["detail"] == "订单不存在：order_no={}".format(
        OTHER_MASTER_ORDER_NO
    )
    assert _normalize_order_no(foreign.json()["detail"]) == _normalize_order_no(
        missing.json()["detail"]
    )

    # 没有泄露归属信息：别家师傅 id、别家服务商 id 都不出现在响应里
    assert str(OTHER_MASTER_ID) not in foreign.text
    assert str(OTHER_PROVIDER_ID) not in foreign.text

    # 订单没被动过
    order = await _order_of(db, OTHER_MASTER_ORDER_ID)
    assert order.status == OrderStatus.PENDING_ACCEPT
    assert order.provider_id == OTHER_PROVIDER_ID
    assert order.master_id == OTHER_MASTER_ID
    assert order.accepted_at is None
    assert await _logs_of(db, OTHER_MASTER_ORDER_ID) == []


@pytest.mark.integration
async def test_accept_nonexistent_order_returns_404(api_client, seeded, db) -> None:
    """订单不存在 -> 404。"""
    response = await api_client.post(
        _accept_url(MISSING_ORDER_NO),
        headers=_my_master_header(),
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "订单不存在：order_no={}".format(
        MISSING_ORDER_NO
    )


@pytest.mark.integration
async def test_accept_order_not_dispatched_to_me_returns_404(
    api_client, seeded, db
) -> None:
    """还没派给我的订单 -> 404，订单没被动过。"""
    response = await api_client.post(
        _accept_url(NOT_DISPATCHED_ORDER_NO),
        headers=_my_master_header(),
    )
    assert response.status_code == 404

    order = await _order_of(db, NOT_DISPATCHED_ORDER_ID)
    assert order.status == OrderStatus.PENDING_DISPATCH
    assert order.provider_id is None
    assert order.master_id is None
    assert await _logs_of(db, NOT_DISPATCHED_ORDER_ID) == []


@pytest.mark.integration
async def test_accept_already_accepted_order_returns_404(
    api_client, seeded, db
) -> None:
    """已经接单的订单再接 -> 404（状态不对与「不存在」同构）。"""
    response = await api_client.post(
        _accept_url(ACCEPTED_ORDER_NO),
        headers=_my_master_header(),
    )
    assert response.status_code == 404

    order = await _order_of(db, ACCEPTED_ORDER_ID)
    assert order.status == OrderStatus.ACCEPTED
    assert await _logs_of(db, ACCEPTED_ORDER_ID) == []


@pytest.mark.integration
async def test_all_failure_responses_are_isomorphic(api_client, seeded) -> None:
    """四种失败（别家的单 / 不存在 / 没派给我 / 状态不对）响应结构完全一致。

    调用方不能靠报错差异判断某个订单号存不存在、派给了谁、处于什么状态。
    """
    responses = []
    for order_no in (
        OTHER_MASTER_ORDER_NO,
        MISSING_ORDER_NO,
        NOT_DISPATCHED_ORDER_NO,
        ACCEPTED_ORDER_NO,
        UNPAID_ORDER_NO,
    ):
        response = await api_client.post(
            _accept_url(order_no),
            headers=_my_master_header(),
        )
        assert response.status_code == 404
        responses.append(_normalize_order_no(response.json()["detail"]))

    assert len(set(responses)) == 1


# ---------------------------------------------------------------------
# 3. 拒单 -> 回 PENDING_DISPATCH，master_id 空，reason 有值
# ---------------------------------------------------------------------


@pytest.mark.integration
async def test_reject_order_returns_to_pending_dispatch(
    api_client, seeded, db
) -> None:
    """拒单 -> 200，订单退回「待派单」，清空承接师傅，reason 落进日志。"""
    response = await api_client.post(
        _reject_url(MY_ORDER_NO),
        json={"reason": "今天有别的单"},
        headers=_my_master_header(),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["order_no"] == MY_ORDER_NO
    assert body["status"] == OrderStatus.PENDING_DISPATCH.value
    assert body["master_id"] is None

    order = await _order_of(db, MY_ORDER_ID)
    assert order.status == OrderStatus.PENDING_DISPATCH
    assert order.master_id is None
    # 归属服务商不变：拒单不改变订单归谁，否则订单会从服务商手里漏出去（R1）
    assert order.provider_id == MY_PROVIDER_ID

    logs = await _logs_of(db, MY_ORDER_ID)
    assert len(logs) == 1
    assert logs[0].from_status == OrderStatus.PENDING_ACCEPT
    assert logs[0].to_status == OrderStatus.PENDING_DISPATCH
    assert logs[0].operator_type == OperatorType.MASTER
    assert logs[0].operator_id == MY_MASTER_USER_ID
    assert logs[0].reason == "今天有别的单"


@pytest.mark.integration
async def test_reject_other_masters_order_returns_404(api_client, seeded, db) -> None:
    """拒别人的单 -> 404，且与「订单不存在」同构；订单没被动过。"""
    foreign = await api_client.post(
        _reject_url(OTHER_MASTER_ORDER_NO),
        json={"reason": "不接"},
        headers=_my_master_header(),
    )
    missing = await api_client.post(
        _reject_url(MISSING_ORDER_NO),
        json={"reason": "不接"},
        headers=_my_master_header(),
    )
    assert foreign.status_code == 404
    assert missing.status_code == 404
    assert _normalize_order_no(foreign.json()["detail"]) == _normalize_order_no(
        missing.json()["detail"]
    )

    order = await _order_of(db, OTHER_MASTER_ORDER_ID)
    assert order.status == OrderStatus.PENDING_ACCEPT
    assert order.master_id == OTHER_MASTER_ID
    assert await _logs_of(db, OTHER_MASTER_ORDER_ID) == []


@pytest.mark.integration
async def test_reject_requires_reason(api_client, seeded, db) -> None:
    """拒单没给 reason -> 422，订单没被动过。"""
    response = await api_client.post(
        _reject_url(MY_ORDER_NO),
        json={},
        headers=_my_master_header(),
    )
    assert response.status_code == 422

    order = await _order_of(db, MY_ORDER_ID)
    assert order.status == OrderStatus.PENDING_ACCEPT
    assert order.master_id == MY_MASTER_ID
    assert await _logs_of(db, MY_ORDER_ID) == []


# ---------------------------------------------------------------------
# 4. 并发接同一笔 -> 成功 1 个，失败 1 个，留痕只有 1 条
# ---------------------------------------------------------------------


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


def _touches_order(statement) -> bool:
    """判断这条语句是不是作用在 order 表上（SELECT 或 UPDATE）。

    会合点必须落在「实现第一次碰到 order 表」的位置，而不是某个具体语句：
    - 读-改-写的实现里，第一句碰到 order 表的是 SELECT；
    - 条件 UPDATE 的实现里，第一句碰到 order 表的是 UPDATE。
    落在固定语句上，只能强制其中一种实现交错 —— 另一种实现会被放过，
    变异测试就会假绿（这坑上一张卡踩过）。

    SELECT 按 ORM 实体判断，不能按语句文本里有没有 "order"：
    order 表有个 master_id 列，按文本判断会把查 master 也算进来。
    UPDATE 没有 column_descriptions，改看它作用的表。
    """
    if isinstance(statement, Select):
        try:
            return statement.column_descriptions[0].get("entity") is Order
        except Exception:  # noqa: BLE001 - 认不出来就当不是
            return False
    table = getattr(statement, "table", None)
    return table is not None and getattr(table, "name", None) == "order"


class _RendezvousSession:
    """在「第一次碰到 order 表」处会合的会话包装。

    作用是把两个并发接单强制排在同一个时间窗里，好让竞态出现：
    - 读-改-写的实现下，两个协程都会先读到「还等着我接单」，
      然后各自改一遍 -> 丢更新，两边都成功、写出两条日志；
    - 条件 UPDATE 的实现下，两个协程同时改，由数据库的行锁裁决，
      只有一方能改成功。
    """

    def __init__(self, session, rendezvous: _Rendezvous) -> None:
        self._session = session
        self._rendezvous = rendezvous
        self._armed = True

    async def execute(self, statement, *args, **kwargs):
        if self._armed and _touches_order(statement):
            # 每个会话只拦一次：拦第二次会把自己也卡住
            self._armed = False
            await self._rendezvous.wait()
        return await self._session.execute(statement, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._session, name)


@pytest.mark.integration
async def test_concurrent_accept_only_one_wins(db, seeded) -> None:
    """同一个师傅同时接同一笔订单：只有一个成功，留痕只有一条。

    条件 UPDATE 下，后到的那一方等前一方提交后重新求值谓词，
    发现订单已经不是「待接单」，于是影响 0 行、按「订单不存在」处理（404）。
    """
    rendezvous = _Rendezvous()
    maker = async_sessionmaker(db, class_=AsyncSession, expire_on_commit=False)

    async def _accept() -> str:
        async with maker() as raw_session:
            session = _RendezvousSession(raw_session, rendezvous)
            current = CurrentUser(
                user_id=MY_MASTER_USER_ID,
                role=UserRole.MASTER,
                provider_id=None,
            )
            try:
                await accept_order(session, order_no=MY_ORDER_NO, current_user=current)
                return "ok"
            except Exception as exc:  # noqa: BLE001 - 只取异常类型名做断言
                return type(exc).__name__

    results = await asyncio.gather(_accept(), _accept())

    assert sorted(results) == ["OrderNotFoundError", "ok"], results

    order = await _order_of(db, MY_ORDER_ID)
    assert order.status == OrderStatus.ACCEPTED
    assert order.master_id == MY_MASTER_ID

    # 留痕只有一条：没有丢更新，也没有写出两条日志
    logs = await _logs_of(db, MY_ORDER_ID)
    assert len(logs) == 1
    assert logs[0].to_status == OrderStatus.ACCEPTED


@pytest.mark.integration
async def test_concurrent_reject_only_one_wins(db, seeded) -> None:
    """同一个师傅同时拒同一笔订单：只有一个成功，留痕只有一条。"""
    rendezvous = _Rendezvous()
    maker = async_sessionmaker(db, class_=AsyncSession, expire_on_commit=False)

    async def _reject() -> str:
        async with maker() as raw_session:
            session = _RendezvousSession(raw_session, rendezvous)
            current = CurrentUser(
                user_id=MY_MASTER_USER_ID,
                role=UserRole.MASTER,
                provider_id=None,
            )
            try:
                await reject_order(
                    session,
                    order_no=MY_ORDER_NO,
                    reason="忙不过来",
                    current_user=current,
                )
                return "ok"
            except Exception as exc:  # noqa: BLE001 - 只取异常类型名做断言
                return type(exc).__name__

    results = await asyncio.gather(_reject(), _reject())

    assert sorted(results) == ["OrderNotFoundError", "ok"], results

    order = await _order_of(db, MY_ORDER_ID)
    assert order.status == OrderStatus.PENDING_DISPATCH
    assert order.master_id is None
    assert len(await _logs_of(db, MY_ORDER_ID)) == 1


# ---------------------------------------------------------------------
# 5. 拒单后可重新派给同一师傅
# ---------------------------------------------------------------------


@pytest.mark.integration
async def test_rejected_order_can_be_dispatched_again_to_same_master(
    api_client, seeded, db
) -> None:
    """拒单后订单回到本商待派单池，可以重新派给同一个师傅。

    归属服务商全程不变（provider_id 一直是本商）。
    """
    reject_response = await api_client.post(
        _reject_url(MY_ORDER_NO),
        json={"reason": "临时有事"},
        headers=_my_master_header(),
    )
    assert reject_response.status_code == 200

    dispatch_response = await api_client.post(
        _dispatch_url(MY_ORDER_ID),
        json={"master_id": MY_MASTER_ID},
        headers=_my_admin_header(),
    )
    assert dispatch_response.status_code == 200
    body = dispatch_response.json()
    assert body["status"] == OrderStatus.PENDING_ACCEPT.value
    assert body["master_id"] == MY_MASTER_ID

    order = await _order_of(db, MY_ORDER_ID)
    assert order.status == OrderStatus.PENDING_ACCEPT
    assert order.master_id == MY_MASTER_ID
    assert order.provider_id == MY_PROVIDER_ID

    # 留痕两条：拒单 + 重新派单
    logs = await _logs_of(db, MY_ORDER_ID)
    assert len(logs) == 2
    assert logs[0].to_status == OrderStatus.PENDING_DISPATCH
    assert logs[1].to_status == OrderStatus.PENDING_ACCEPT


@pytest.mark.integration
async def test_rejected_order_can_be_dispatched_to_another_master(
    api_client, seeded, db
) -> None:
    """拒单后可以改派给本商另一个师傅（订单仍在本商手里）。"""
    reject_response = await api_client.post(
        _reject_url(MY_ORDER_NO),
        json={"reason": "临时有事"},
        headers=_my_master_header(),
    )
    assert reject_response.status_code == 200

    dispatch_response = await api_client.post(
        _dispatch_url(MY_ORDER_ID),
        json={"master_id": MY_OTHER_MASTER_ID},
        headers=_my_admin_header(),
    )
    assert dispatch_response.status_code == 200
    assert dispatch_response.json()["master_id"] == MY_OTHER_MASTER_ID

    order = await _order_of(db, MY_ORDER_ID)
    assert order.status == OrderStatus.PENDING_ACCEPT
    assert order.master_id == MY_OTHER_MASTER_ID
    assert order.provider_id == MY_PROVIDER_ID


@pytest.mark.integration
async def test_rejected_order_cannot_be_dispatched_to_other_provider(
    api_client, seeded, db
) -> None:
    """拒单后订单仍归本商，别家服务商不能把它抢走（R1）。

    别家派单同样会撞上 dispatch 的归属校验：订单的 provider_id 已经不是空，
    与 dispatch 的归属不变式一致。
    """
    reject_response = await api_client.post(
        _reject_url(MY_ORDER_NO),
        json={"reason": "临时有事"},
        headers=_my_master_header(),
    )
    assert reject_response.status_code == 200

    dispatch_response = await api_client.post(
        _dispatch_url(MY_ORDER_ID),
        json={"master_id": OTHER_MASTER_ID},
        headers=_auth_header(
            OTHER_ADMIN_USER_ID, UserRole.PROVIDER_ADMIN, OTHER_PROVIDER_ID
        ),
    )
    assert dispatch_response.status_code == 404

    order = await _order_of(db, MY_ORDER_ID)
    assert order.provider_id == MY_PROVIDER_ID
    assert order.master_id is None
    assert order.status == OrderStatus.PENDING_DISPATCH


# ---------------------------------------------------------------------
# 其余边界
# ---------------------------------------------------------------------


@pytest.mark.integration
async def test_account_without_master_identity_cannot_accept(
    api_client, seeded, db
) -> None:
    """没有师傅身份的账号（服务商管理员）接单 -> 403，订单没被动过。"""
    response = await api_client.post(
        _accept_url(MY_ORDER_NO),
        headers=_my_admin_header(),
    )
    assert response.status_code == 403
    assert response.json() == {"detail": "当前账号没有师傅身份"}

    order = await _order_of(db, MY_ORDER_ID)
    assert order.status == OrderStatus.PENDING_ACCEPT
    assert await _logs_of(db, MY_ORDER_ID) == []


@pytest.mark.integration
async def test_account_without_master_identity_cannot_reject(
    api_client, seeded, db
) -> None:
    """没有师傅身份的账号拒单 -> 403。"""
    response = await api_client.post(
        _reject_url(MY_ORDER_NO),
        json={"reason": "不接"},
        headers=_my_admin_header(),
    )
    assert response.status_code == 403

    order = await _order_of(db, MY_ORDER_ID)
    assert order.status == OrderStatus.PENDING_ACCEPT
    assert await _logs_of(db, MY_ORDER_ID) == []


@pytest.mark.integration
async def test_inconsistent_master_identity_cannot_accept(
    api_client, seeded, db
) -> None:
    """账号身份错乱（服务商归属与师傅归属不一致）-> 403。

    这条守的是已知技术债的另一半：master 表说这个账号是别家师傅，
    token 里的 provider_id 却说他是本商管理员。两边对不上时，
    这个账号不能动任何订单——它到底是谁都说不清。
    """
    response = await api_client.post(
        _accept_url(MY_ORDER_NO),
        headers=_auth_header(
            MISMATCHED_USER_ID, UserRole.PROVIDER_ADMIN, MY_PROVIDER_ID
        ),
    )
    assert response.status_code == 403
    assert response.json() == {"detail": "当前账号的师傅身份与服务商归属不一致"}

    order = await _order_of(db, MY_ORDER_ID)
    assert order.status == OrderStatus.PENDING_ACCEPT
    assert await _logs_of(db, MY_ORDER_ID) == []


@pytest.mark.integration
async def test_accept_requires_authentication(api_client, seeded) -> None:
    """没带 token -> 401。"""
    response = await api_client.post(_accept_url(MY_ORDER_NO))
    assert response.status_code == 401


@pytest.mark.integration
async def test_accept_transition_goes_through_state_machine(
    api_client, seeded, monkeypatch
) -> None:
    """R4：状态流转必须经过状态机（assert_transition 被调用）。"""
    calls = []

    def _spy(from_status, to_status):
        calls.append((from_status, to_status))
        return real_assert_transition(from_status, to_status)

    monkeypatch.setattr(master_action_module, "assert_transition", _spy)

    response = await api_client.post(
        _accept_url(MY_ORDER_NO),
        headers=_my_master_header(),
    )
    assert response.status_code == 200
    assert calls == [(OrderStatus.PENDING_ACCEPT, OrderStatus.ACCEPTED)]


@pytest.mark.integration
async def test_reject_transition_goes_through_state_machine(
    api_client, seeded, monkeypatch
) -> None:
    """拒单也走状态机：PENDING_ACCEPT -> PENDING_DISPATCH 是合法流转。"""
    calls = []

    def _spy(from_status, to_status):
        calls.append((from_status, to_status))
        return real_assert_transition(from_status, to_status)

    monkeypatch.setattr(master_action_module, "assert_transition", _spy)

    response = await api_client.post(
        _reject_url(MY_ORDER_NO),
        json={"reason": "忙"},
        headers=_my_master_header(),
    )
    assert response.status_code == 200
    assert calls == [(OrderStatus.PENDING_ACCEPT, OrderStatus.PENDING_DISPATCH)]


@pytest.mark.integration
async def test_invalid_transition_writes_nothing(
    api_client, seeded, db, monkeypatch
) -> None:
    """变异验证：assert_transition 抛异常时，订单状态与留痕都不许被写。"""

    def _boom(from_status, to_status):
        raise OrderTransitionError(from_status, to_status)

    monkeypatch.setattr(master_action_module, "assert_transition", _boom)

    response = await api_client.post(
        _accept_url(MY_ORDER_NO),
        headers=_my_master_header(),
    )
    # OrderTransitionError 不在业务异常树里，原样冒泡成 500
    assert response.status_code == 500

    order = await _order_of(db, MY_ORDER_ID)
    assert order.status == OrderStatus.PENDING_ACCEPT
    assert order.accepted_at is None
    assert await _logs_of(db, MY_ORDER_ID) == []
