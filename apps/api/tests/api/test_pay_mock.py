"""mock 支付回调接口的测试。

分两类：

- **单元测试**（不碰数据库）：schema 字段集合、环境开关、
  「非 dev 环境不触达 service」；
- **集成测试**（需要真实 PostgreSQL）：真的走 HTTP -> service -> 数据库，
  验证 200 / 404 / 409、幂等、状态流转留痕、金额不变。

集成测试用的数据库是 TEST_DATABASE_URL 指向的独立测试库
（集成 fixture 每次 drop_all + create_all，绝不碰开发库）。
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.api.v1.pay as pay_module
import app.services.pay_mock as pay_mock_module
from tests.support import business_today
from app.core.config import settings
from app.core.database import get_session
from app.domain.order_state import OrderTransitionError
from app.domain.order_state import assert_transition as real_assert_transition
from app.main import app
from app.models.address import Address
from app.models.base import Base
from app.models.catalog import ServiceCategory, ServiceItem
from app.models.enums import OperatorType, OrderStatus, PayStatus
from app.models.order import Order, OrderStatusLog
from app.models.schedule_slot import ScheduleSlot
from app.models.user import User
from app.schemas.pay import MockPayNotifyRequest, MockPayResult
from app.services.errors import InvalidOrderStateError, OrderNotFoundError
from app.services.pay_mock import mock_pay_success

MOCK_URL = "/api/v1/pay/mock-notify"
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

# 种子数据里的订单号
PENDING_PAY_ORDER_NO = "OTO20260101000001"
# 已接单、但跳过了支付环节（pay_status 还是 UNPAID）——撞 409
UNPAID_ACCEPTED_ORDER_NO = "OTO20260101000002"
# 已接单且已支付——重复回调走幂等分支
PAID_ACCEPTED_ORDER_NO = "OTO20260101000003"
MISSING_ORDER_NO = "OTO20260101009999"

BASE_PRICE = Decimal("100.00")


# =====================================================================
# 单元测试：schema
# =====================================================================


def test_mock_notify_request_field_set_is_exactly_one() -> None:
    """请求体只有一个字段：order_no。

    用集合相等而不是「包含」：多一个字段（比如 amount）直接失败。
    """
    assert set(MockPayNotifyRequest.model_fields) == {"order_no"}


def test_mock_notify_request_has_no_business_fields() -> None:
    """请求体里不得出现金额、状态这类业务字段。"""
    forbidden = {"amount", "status", "pay_status", "user_id", "provider_id"}
    assert forbidden.isdisjoint(MockPayNotifyRequest.model_fields)


def test_mock_notify_request_rejects_extra_fields() -> None:
    """extra="forbid"：带多余字段直接抛校验错误。"""
    with pytest.raises(Exception):
        MockPayNotifyRequest(order_no="OTO1", amount=1)


def test_mock_result_field_set_is_exactly_three() -> None:
    """响应恰好三个字段：order_no / status / pay_status。"""
    assert set(MockPayResult.model_fields) == {"order_no", "status", "pay_status"}


# =====================================================================
# 单元测试：环境开关
# =====================================================================


@pytest.fixture
async def client():
    """不接数据库的 HTTP 客户端。

    用于「请求到不了业务逻辑」的用例（环境开关、请求体校验失败）
    以及把 service 替换成假实现的异常映射用例。
    """

    async def override_get_session():
        # 用例里用到的 service 都被替换掉了，这里给不出真实会话也没关系
        yield None

    app.dependency_overrides[get_session] = override_get_session
    try:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as http_client:
            yield http_client
    finally:
        app.dependency_overrides.pop(get_session, None)


async def test_mock_endpoint_returns_403_when_app_env_is_not_dev(
    client, monkeypatch
) -> None:
    """APP_ENV 不是 dev -> 403，且**不触达 service**。

    用打桩的 service 记录调用次数：只要它被调过，这个用例就失败。
    """
    calls = []

    async def _spy(session, *, order_no):
        calls.append(order_no)
        raise AssertionError("非 dev 环境不该触达 service")

    monkeypatch.setattr(settings, "app_env", "prod")
    monkeypatch.setattr(pay_module, "mock_pay_success", _spy)

    response = await client.post(MOCK_URL, json={"order_no": PENDING_PAY_ORDER_NO})

    assert response.status_code == 403
    assert response.json() == {"detail": "mock endpoint disabled in non-dev"}
    assert calls == []


async def test_mock_endpoint_is_open_in_dev(client, monkeypatch) -> None:
    """APP_ENV=dev -> 请求确实打到了 service，并按 service 的返回值回响应。"""
    calls = []

    async def _fake(session, *, order_no):
        calls.append(order_no)
        return _FakeOrder()

    monkeypatch.setattr(settings, "app_env", "dev")
    monkeypatch.setattr(pay_module, "mock_pay_success", _fake)

    response = await client.post(MOCK_URL, json={"order_no": PENDING_PAY_ORDER_NO})

    assert response.status_code == 200
    assert calls == [PENDING_PAY_ORDER_NO]
    assert response.json() == {
        "order_no": PENDING_PAY_ORDER_NO,
        "status": OrderStatus.PENDING_DISPATCH.value,
        "pay_status": PayStatus.PAID.value,
    }


class _FakeOrder:
    """假订单：只带 router 要用的三个属性。"""

    order_no = PENDING_PAY_ORDER_NO
    status = OrderStatus.PENDING_DISPATCH
    pay_status = PayStatus.PAID


# =====================================================================
# 单元测试：异常 -> HTTP 状态码（service 被替换成抛异常的假实现）
# =====================================================================


@pytest.mark.parametrize(
    "exc, expected_status",
    [
        (OrderNotFoundError("订单不存在"), 404),
        (InvalidOrderStateError("状态不对"), 409),
    ],
)
async def test_service_exception_maps_to_status(
    client, monkeypatch, exc, expected_status
) -> None:
    """service 抛业务异常 -> 对应的 HTTP 状态码。"""

    async def _raise(*args, **kwargs):
        raise exc

    monkeypatch.setattr(settings, "app_env", "dev")
    monkeypatch.setattr(pay_module, "mock_pay_success", _raise)
    response = await client.post(MOCK_URL, json={"order_no": PENDING_PAY_ORDER_NO})
    assert response.status_code == expected_status


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


@dataclass
class Seed:
    user_id: int
    item_id: int
    slot_id: int
    address_id: int
    pending_pay_order_id: int
    unpaid_accepted_order_id: int
    paid_accepted_order_id: int
    base_price: Decimal


@pytest.fixture
async def seeded(db) -> Seed:
    """种三笔订单：

    - 待支付（正常流程的起点）；
    - 已接单但没走过支付环节（pay_status=UNPAID）——撞 409；
    - 已接单且已支付——重复回调走幂等分支。
    """
    maker = async_sessionmaker(db, class_=AsyncSession, expire_on_commit=False)
    tomorrow = business_today() + timedelta(days=1)
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
                base_price=BASE_PRICE,
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
        await session.flush()
        pending = Order(
            order_no=PENDING_PAY_ORDER_NO,
            user_id=1,
            provider_id=None,
            master_id=None,
            address_id=4,
            item_id=2,
            slot_id=3,
            amount=BASE_PRICE,
            status=OrderStatus.PENDING_PAY,
            pay_status=PayStatus.UNPAID,
        )
        unpaid_accepted = Order(
            order_no=UNPAID_ACCEPTED_ORDER_NO,
            user_id=1,
            provider_id=None,
            master_id=None,
            address_id=4,
            item_id=2,
            slot_id=3,
            amount=BASE_PRICE,
            status=OrderStatus.ACCEPTED,
            pay_status=PayStatus.UNPAID,
        )
        paid_accepted = Order(
            order_no=PAID_ACCEPTED_ORDER_NO,
            user_id=1,
            provider_id=None,
            master_id=None,
            address_id=4,
            item_id=2,
            slot_id=3,
            amount=BASE_PRICE,
            status=OrderStatus.ACCEPTED,
            pay_status=PayStatus.PAID,
            paid_at=datetime.now(timezone.utc),
        )
        session.add_all([pending, unpaid_accepted, paid_accepted])
        await session.flush()
        await session.commit()
        pending_id = pending.id
        unpaid_accepted_id = unpaid_accepted.id
        paid_accepted_id = paid_accepted.id
    return Seed(
        user_id=1,
        item_id=2,
        slot_id=3,
        address_id=4,
        pending_pay_order_id=pending_id,
        unpaid_accepted_order_id=unpaid_accepted_id,
        paid_accepted_order_id=paid_accepted_id,
        base_price=BASE_PRICE,
    )


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


async def _logs_of(db, order_id: int) -> list[OrderStatusLog]:
    maker = _maker(db)
    async with maker() as session:
        rows = (
            await session.execute(
                select(OrderStatusLog).where(OrderStatusLog.order_id == order_id)
            )
        ).scalars().all()
        return list(rows)


@pytest.mark.integration
async def test_mock_pay_success_transitions_order(
    api_client, seeded, db, monkeypatch
) -> None:
    """待支付订单 -> 200，状态推进到待派单，支付状态为已支付，并留痕。"""
    monkeypatch.setattr(settings, "app_env", "dev")
    response = await api_client.post(
        MOCK_URL, json={"order_no": PENDING_PAY_ORDER_NO}
    )
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"order_no", "status", "pay_status"}
    assert body["order_no"] == PENDING_PAY_ORDER_NO
    assert body["status"] == OrderStatus.PENDING_DISPATCH.value
    assert body["pay_status"] == PayStatus.PAID.value

    maker = _maker(db)
    async with maker() as session:
        order = (
            await session.execute(
                select(Order).where(Order.id == seeded.pending_pay_order_id)
            )
        ).scalar_one()
        assert order.status == OrderStatus.PENDING_DISPATCH
        assert order.pay_status == PayStatus.PAID
        assert order.paid_at is not None

    logs = await _logs_of(db, seeded.pending_pay_order_id)
    assert len(logs) == 1
    assert logs[0].from_status == OrderStatus.PENDING_PAY
    assert logs[0].to_status == OrderStatus.PENDING_DISPATCH
    assert logs[0].operator_type == OperatorType.SYSTEM
    assert logs[0].operator_id == 0
    assert logs[0].reason == "mock 支付成功"


@pytest.mark.integration
async def test_mock_pay_is_idempotent(api_client, seeded, db, monkeypatch) -> None:
    """连续调两次：第二次不重复写日志、不重复改 pay_status。"""
    monkeypatch.setattr(settings, "app_env", "dev")

    first = await api_client.post(MOCK_URL, json={"order_no": PENDING_PAY_ORDER_NO})
    assert first.status_code == 200
    first_paid_at = None
    maker = _maker(db)
    async with maker() as session:
        order = (
            await session.execute(
                select(Order).where(Order.id == seeded.pending_pay_order_id)
            )
        ).scalar_one()
        first_paid_at = order.paid_at

    second = await api_client.post(MOCK_URL, json={"order_no": PENDING_PAY_ORDER_NO})
    assert second.status_code == 200
    assert second.json()["status"] == OrderStatus.PENDING_DISPATCH.value
    assert second.json()["pay_status"] == PayStatus.PAID.value

    # 状态流转日志只有一条：幂等分支不写日志
    logs = await _logs_of(db, seeded.pending_pay_order_id)
    assert len(logs) == 1

    # pay_status 仍是已支付，paid_at 没有被第二次回调刷新
    async with maker() as session:
        order = (
            await session.execute(
                select(Order).where(Order.id == seeded.pending_pay_order_id)
            )
        ).scalar_one()
        assert order.pay_status == PayStatus.PAID
        assert order.paid_at == first_paid_at


@pytest.mark.integration
async def test_missing_order_returns_404(api_client, monkeypatch) -> None:
    """订单不存在 -> 404。"""
    monkeypatch.setattr(settings, "app_env", "dev")
    response = await api_client.post(MOCK_URL, json={"order_no": MISSING_ORDER_NO})
    assert response.status_code == 404
    assert "detail" in response.json()


@pytest.mark.integration
async def test_order_not_pending_pay_returns_409(
    api_client, seeded, db, monkeypatch
) -> None:
    """订单已跳过支付环节（状态是已接单、pay_status 还是未支付）-> 409，且不写日志。"""
    monkeypatch.setattr(settings, "app_env", "dev")
    response = await api_client.post(
        MOCK_URL, json={"order_no": UNPAID_ACCEPTED_ORDER_NO}
    )
    assert response.status_code == 409

    maker = _maker(db)
    async with maker() as session:
        order = (
            await session.execute(
                select(Order).where(Order.id == seeded.unpaid_accepted_order_id)
            )
        ).scalar_one()
        assert order.status == OrderStatus.ACCEPTED
        assert order.pay_status == PayStatus.UNPAID

    # 状态没变，就不该留下状态流转日志
    assert await _logs_of(db, seeded.unpaid_accepted_order_id) == []


@pytest.mark.integration
async def test_paid_order_is_idempotent_no_matter_how_far_it_progressed(
    api_client, seeded, db, monkeypatch
) -> None:
    """已支付且已推进到后面的订单（这里直接跳到已接单）-> 200 幂等，不改状态、不写日志。

    支付回调可能被第三方重复投递，只要这笔钱已经到账、订单也已经推进过，
    再来一次就是空操作。
    """
    monkeypatch.setattr(settings, "app_env", "dev")
    response = await api_client.post(
        MOCK_URL, json={"order_no": PAID_ACCEPTED_ORDER_NO}
    )
    assert response.status_code == 200
    assert response.json()["status"] == OrderStatus.ACCEPTED.value
    assert response.json()["pay_status"] == PayStatus.PAID.value

    maker = _maker(db)
    async with maker() as session:
        order = (
            await session.execute(
                select(Order).where(Order.id == seeded.paid_accepted_order_id)
            )
        ).scalar_one()
        # 状态没有被拉回「待派单」，支付状态也没变
        assert order.status == OrderStatus.ACCEPTED
        assert order.pay_status == PayStatus.PAID

    assert await _logs_of(db, seeded.paid_accepted_order_id) == []


@pytest.mark.integration
async def test_mock_pay_does_not_change_amount(api_client, seeded, db, monkeypatch) -> None:
    """mock 回调不重新定价：订单金额保持下单时的快照值。"""
    monkeypatch.setattr(settings, "app_env", "dev")
    response = await api_client.post(MOCK_URL, json={"order_no": PENDING_PAY_ORDER_NO})
    assert response.status_code == 200
    # 响应里根本没有金额字段
    assert "amount" not in response.json()

    maker = _maker(db)
    async with maker() as session:
        order = (
            await session.execute(
                select(Order).where(Order.id == seeded.pending_pay_order_id)
            )
        ).scalar_one()
        assert order.amount == seeded.base_price


@pytest.mark.integration
async def test_transition_goes_through_state_machine(
    api_client, seeded, monkeypatch
) -> None:
    """R4：状态流转必须经过状态机（assert_transition 被调用）。

    把 assert_transition 换成「记录调用后再调真的」的探针，
    断言它确实被调用过，且参数是 (PENDING_PAY, PENDING_DISPATCH)。
    """
    calls = []

    def _spy(from_status, to_status):
        calls.append((from_status, to_status))
        return real_assert_transition(from_status, to_status)

    monkeypatch.setattr(settings, "app_env", "dev")
    monkeypatch.setattr(pay_mock_module, "assert_transition", _spy)

    response = await api_client.post(MOCK_URL, json={"order_no": PENDING_PAY_ORDER_NO})
    assert response.status_code == 200
    assert calls == [(OrderStatus.PENDING_PAY, OrderStatus.PENDING_DISPATCH)]


@pytest.mark.integration
async def test_invalid_transition_writes_nothing(db, seeded, monkeypatch) -> None:
    """变异验证：assert_transition 抛异常时，订单状态与日志都不许被写。

    这是 R4 的反向验证——证明 service 没有在状态机之外偷偷改状态：
    把状态机换成「一律抛异常」，service 必须原样抛出来，
    且数据库里订单状态不变、支付状态不变、没有状态流转日志。
    """

    def _boom(from_status, to_status):
        raise OrderTransitionError(from_status, to_status)

    monkeypatch.setattr(pay_mock_module, "assert_transition", _boom)

    maker = _maker(db)
    async with maker() as session:
        with pytest.raises(OrderTransitionError):
            await mock_pay_success(session, order_no=PENDING_PAY_ORDER_NO)

    async with maker() as session:
        order = (
            await session.execute(
                select(Order).where(Order.id == seeded.pending_pay_order_id)
            )
        ).scalar_one()
        # 状态没变、支付状态没变、支付时间没写
        assert order.status == OrderStatus.PENDING_PAY
        assert order.pay_status == PayStatus.UNPAID
        assert order.paid_at is None

    assert await _logs_of(db, seeded.pending_pay_order_id) == []
