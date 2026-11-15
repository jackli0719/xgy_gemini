"""下单接口层的测试。

分两类：

- **单元测试**（不碰数据库）：schema 字段集合、401 的三种失败、
  422 的越权字段、异常映射表；
- **集成测试**（需要真实 PostgreSQL）：真的走 HTTP -> service -> 数据库，
  验证 201 / 404 / 409。

集成测试用的数据库是 TEST_DATABASE_URL 指向的独立测试库
（集成 fixture 每次 drop_all + create_all，绝不碰开发库）。
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import date, time, timedelta
from decimal import Decimal

import httpx
import jwt
import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.api.v1.orders as orders_module
from app.api.v1.errors import EXCEPTION_STATUS_MAP, status_for
from app.core.auth import create_access_token
from app.core.config import settings
from app.core.database import get_session
from app.domain.pricing import PricingError
from app.domain.slot_rule import SlotInvalidError, SlotNotReservableError
from app.main import app
from app.models.address import Address
from app.models.base import Base
from app.models.catalog import ServiceCategory, ServiceItem
from app.models.enums import CatalogStatus, OrderStatus, UserRole
from app.models.order import Order
from app.models.schedule_slot import ScheduleSlot
from app.models.user import User
from app.schemas.order import PlaceOrderRequest
from app.services.errors import (
    AddressInUseError,
    AddressNotFoundError,
    CatalogError,
    CatalogNotFoundError,
    DispatchError,
    DispatchForbiddenError,
    InvalidOrderStateError,
    ItemInactiveError,
    ItemNotFoundError,
    MasterActionError,
    MasterActionForbiddenError,
    MasterActionInvariantError,
    MasterNotDispatchableError,
    MasterNotFoundError,
    MasterOrderStatusNotAllowedError,
    MasterQueryError,
    MasterQueryForbiddenError,
    MasterStatusNotSettableError,
    OrderNoConflictError,
    OrderNotFoundError,
    PlaceOrderError,
    PlatformProviderConflictError,
    PlatformProviderError,
    PlatformProviderForbiddenError,
    PlatformProviderNotFoundError,
    PlatformProviderStatusNotSettableError,
    ServiceFlowError,
    ServiceFlowForbiddenError,
    ServiceFlowInvariantError,
    SettlementError,
    SettlementForbiddenError,
    SettlementInvariantError,
    SettlementNotFoundError,
    SlotItemMismatchError,
    SlotNotFoundError,
    SlotNotInFutureError,
)

ORDER_URL = "/api/v1/orders"
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

# 用来伪造"别的密钥签的 token"。同样要满足 RFC 7518 对 HS256 的 32 字节下限，
# 否则 PyJWT 会发 InsecureKeyLengthWarning，把真正的密钥长度问题淹没在噪声里。
_WRONG_SECRET = "wrong-secret-for-negative-tests-only-0123456789abcdef"


# =====================================================================
# 公共小工具
# =====================================================================


def _auth_header(user_id: int, **kwargs) -> dict[str, str]:
    """生成带合法 token 的请求头。

    默认身份是普通 C 端用户（role=USER、provider_id=None）——
    下单接口只认 user_id，测试用不到服务商身份。
    """
    kwargs.setdefault("role", UserRole.USER)
    kwargs.setdefault("provider_id", None)
    token = create_access_token(user_id, **kwargs)
    return {"Authorization": "Bearer {}".format(token)}


def _valid_body(seed: "Seed") -> dict[str, int]:
    """一份合法的下单请求体（用户 A 自己的地址 + 可用时段）。"""
    return {
        "item_id": seed.item_id,
        "slot_id": seed.slot_id,
        "address_id": seed.address_a_id,
    }


# =====================================================================
# 单元测试：schema
# =====================================================================


def test_place_order_request_field_set_is_exactly_three() -> None:
    """请求 schema 的字段集合恰好是 {item_id, slot_id, address_id}。

    用集合相等而不是「包含」：多一个字段（比如 amount / user_id）
    会直接让这条断言失败。
    """
    assert set(PlaceOrderRequest.model_fields) == {
        "item_id",
        "slot_id",
        "address_id",
    }


def test_place_order_request_has_no_business_fields() -> None:
    """请求 schema 里不得出现业务字段。"""
    forbidden = {
        "amount",
        "order_no",
        "status",
        "provider_id",
        "master_id",
        "user_id",
        "price",
        "pay_status",
    }
    assert forbidden.isdisjoint(PlaceOrderRequest.model_fields)


def test_place_order_request_rejects_extra_fields() -> None:
    """extra="forbid"：带多余字段直接抛校验错误。"""
    with pytest.raises(Exception):
        PlaceOrderRequest(item_id=1, slot_id=2, address_id=3, user_id=9)


def test_place_order_request_requires_positive_ids() -> None:
    """三个 ID 都必须 > 0。"""
    for bad in (0, -1):
        with pytest.raises(Exception):
            PlaceOrderRequest(item_id=bad, slot_id=2, address_id=3)
        with pytest.raises(Exception):
            PlaceOrderRequest(item_id=1, slot_id=bad, address_id=3)
        with pytest.raises(Exception):
            PlaceOrderRequest(item_id=1, slot_id=2, address_id=bad)


# =====================================================================
# 单元测试：异常映射表
# =====================================================================


def test_exception_status_map_contents() -> None:
    """映射表就是显式写死的那几张。"""
    assert EXCEPTION_STATUS_MAP == {
        AddressNotFoundError: 404,
        ItemNotFoundError: 404,
        SlotNotFoundError: 404,
        OrderNotFoundError: 404,
        # 地址被订单引用，删不掉
        AddressInUseError: 409,
        ItemInactiveError: 409,
        SlotNotInFutureError: 409,
        SlotItemMismatchError: 409,
        SlotInvalidError: 409,
        SlotNotReservableError: 409,
        InvalidOrderStateError: 409,
        OrderNoConflictError: 503,
        # 派单
        DispatchForbiddenError: 403,
        MasterNotFoundError: 404,
        # 师傅状态管理：状态不允许被设置 -> 改请求内容才可能解决
        MasterStatusNotSettableError: 400,
        # 本商师傅当前不可接单（停用 / 休假 / 未审核）-> 换个师傅是可行的应对
        MasterNotDispatchableError: 409,
        # 师傅接单/拒单
        MasterActionForbiddenError: 403,
        MasterActionInvariantError: 500,
        # 师傅端查询（我的订单 / 我的资料）
        MasterQueryForbiddenError: 403,
        # 师傅端查询：状态不在「三种工作分组」里
        MasterOrderStatusNotAllowedError: 400,
        # 服务流转（开工 / 完工 / 确认完成）
        ServiceFlowForbiddenError: 403,
        ServiceFlowInvariantError: 500,
        # 结算确认（财务确认结算单）
        SettlementForbiddenError: 403,
        SettlementNotFoundError: 404,
        SettlementInvariantError: 500,
        # 目录查询（品类 / 服务项 / 时段）
        CatalogNotFoundError: 404,
        PlaceOrderError: 400,
        DispatchError: 400,
        MasterActionError: 400,
        MasterQueryError: 400,
        ServiceFlowError: 400,
        SettlementError: 400,
        CatalogError: 400,
        # 平台侧服务商管理（PLAT-01）
        PlatformProviderNotFoundError: 404,
        # 状态不允许被设置 -> 改请求内容才可能解决
        PlatformProviderStatusNotSettableError: 400,
        PlatformProviderForbiddenError: 403,
        PlatformProviderConflictError: 409,
        PlatformProviderError: 400,
    }


def test_status_for_prefers_most_specific_subclass() -> None:
    """OrderNoConflictError 是 PlaceOrderError 的子类，必须命中 503 而不是兜底的 400。"""
    assert status_for(OrderNoConflictError("冲突")) == 503
    assert status_for(PlaceOrderError("兜底")) == 400


# =====================================================================
# 单元测试：鉴权（不碰数据库）
# =====================================================================


@pytest.fixture
async def client():
    """不接数据库的 HTTP 客户端。

    只用于「请求到不了业务逻辑」的用例（鉴权失败、请求体校验失败）
    以及把 service 替换成假实现的异常映射用例。
    """
    async def override_get_session():
        # 真正用到的都是被替换掉的 place_order，这里给不出真实会话也没关系
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


async def test_missing_authorization_header_returns_401(client) -> None:
    """缺 Authorization 头 -> 401（不是 422）。"""
    response = await client.post(ORDER_URL, json={"item_id": 1, "slot_id": 2, "address_id": 3})
    assert response.status_code == 401


async def test_invalid_token_returns_401(client) -> None:
    """token 非法（不是 JWT）-> 401。"""
    response = await client.post(
        ORDER_URL,
        json={"item_id": 1, "slot_id": 2, "address_id": 3},
        headers={"Authorization": "Bearer not-a-jwt"},
    )
    assert response.status_code == 401


async def test_token_signed_with_wrong_secret_returns_401(client) -> None:
    """签名不对（用别的密钥签的）-> 401。"""
    from datetime import datetime, timezone

    payload = {
        "sub": "1",
        "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
    }
    forged = jwt.encode(payload, _WRONG_SECRET, algorithm=settings.jwt_alg)
    response = await client.post(
        ORDER_URL,
        json={"item_id": 1, "slot_id": 2, "address_id": 3},
        headers={"Authorization": "Bearer {}".format(forged)},
    )
    assert response.status_code == 401


async def test_expired_token_returns_401(client) -> None:
    """token 过期 -> 401。"""
    response = await client.post(
        ORDER_URL,
        json={"item_id": 1, "slot_id": 2, "address_id": 3},
        headers=_auth_header(1, expires_delta=timedelta(minutes=-5)),
    )
    assert response.status_code == 401


async def test_all_401_responses_share_the_same_detail(client) -> None:
    """四种鉴权失败的响应消息完全一致，不区分原因。"""
    from datetime import datetime, timezone

    forged = jwt.encode(
        {
            "sub": "1",
            "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
        },
        _WRONG_SECRET,
        algorithm=settings.jwt_alg,
    )
    cases = [
        {},  # 缺 header
        {"Authorization": "Bearer not-a-jwt"},  # 格式错
        {"Authorization": "Bearer {}".format(forged)},  # 验签失败
        _auth_header(1, expires_delta=timedelta(minutes=-5)),  # 过期
    ]
    details = []
    for headers in cases:
        response = await client.post(
            ORDER_URL,
            json={"item_id": 1, "slot_id": 2, "address_id": 3},
            headers=headers,
        )
        assert response.status_code == 401
        details.append(response.json())
    assert details[0] == {"detail": "Unauthorized"}
    assert all(item == details[0] for item in details)


async def test_extra_user_id_in_body_returns_422(client) -> None:
    """请求体带 user_id -> 422（schema 直接拒掉）。"""
    response = await client.post(
        ORDER_URL,
        json={"item_id": 1, "slot_id": 2, "address_id": 3, "user_id": 999},
        headers=_auth_header(1),
    )
    assert response.status_code == 422


async def test_extra_amount_in_body_returns_422(client) -> None:
    """请求体带 amount -> 422（金额只能由服务端决定）。"""
    response = await client.post(
        ORDER_URL,
        json={"item_id": 1, "slot_id": 2, "address_id": 3, "amount": 0.01},
        headers=_auth_header(1),
    )
    assert response.status_code == 422


async def test_non_positive_id_returns_422(client) -> None:
    """id <= 0 -> 422。"""
    response = await client.post(
        ORDER_URL,
        json={"item_id": 0, "slot_id": 2, "address_id": 3},
        headers=_auth_header(1),
    )
    assert response.status_code == 422


# =====================================================================
# 单元测试：异常 -> HTTP 状态码（service 被替换成抛异常的假实现）
# =====================================================================


@pytest.mark.parametrize(
    "exc, expected_status",
    [
        (OrderNoConflictError("订单号连续冲突"), 503),
        (PlaceOrderError("兜底业务异常"), 400),
    ],
)
async def test_service_exception_maps_to_status(
    client, monkeypatch, exc, expected_status
) -> None:
    """service 抛业务异常 -> 对应的 HTTP 状态码。"""

    async def _raise(*args, **kwargs):
        raise exc

    monkeypatch.setattr(orders_module, "place_order", _raise)
    response = await client.post(
        ORDER_URL,
        json={"item_id": 1, "slot_id": 2, "address_id": 3},
        headers=_auth_header(1),
    )
    assert response.status_code == expected_status


async def test_pricing_error_is_not_translated_to_4xx(client, monkeypatch) -> None:
    """PricingError 不进映射表：让它冒泡成 500，不翻译成 4xx。

    价格是脏数据属于服务端问题，报成 4xx 会让调用方以为重发请求有用。
    """

    async def _raise(*args, **kwargs):
        raise PricingError("base_price 超过上限")

    monkeypatch.setattr(orders_module, "place_order", _raise)
    response = await client.post(
        ORDER_URL,
        json={"item_id": 1, "slot_id": 2, "address_id": 3},
        headers=_auth_header(1),
    )
    assert response.status_code == 500


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
    user_a_id: int
    user_b_id: int
    item_id: int
    inactive_item_id: int
    slot_id: int
    other_item_slot_id: int
    past_slot_id: int
    address_a_id: int
    address_b_id: int
    capacity: int
    base_price: Decimal


@pytest.fixture
async def seeded(db) -> Seed:
    """铺好下单要用的数据。

    - 用户 A（1）：自己的地址（4）
    - 用户 B（2）：自己的地址（6）
    - 服务项 2（启用）、服务项 5（停用）
    - 时段 3（item 2，明天）、时段 7（item 5）、时段 8（item 2，昨天）
    """
    maker = async_sessionmaker(db, class_=AsyncSession, expire_on_commit=False)
    tomorrow = date.today() + timedelta(days=1)
    yesterday = date.today() - timedelta(days=1)
    async with maker() as session:
        # 模型层没有 relationship，SQLAlchemy 的 flush 顺序按 mapper 类名字母序
        # （不是外键依赖序），所以这里按依赖顺序逐个 flush，避免外键违例
        session.add(User(id=1, phone="13800000001"))
        session.add(User(id=2, phone="13800000002"))
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
                status=CatalogStatus.ACTIVE,
            )
        )
        session.add(
            ServiceItem(
                id=5,
                category_id=1,
                name="已停用服务项",
                base_price=Decimal("100.00"),
                duration_min=60,
                status=CatalogStatus.INACTIVE,
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
        session.add(
            Address(
                id=6,
                user_id=2,
                contact="李四",
                phone="13800000002",
                region="上海",
                detail="某路 2 号",
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
        session.add(
            ScheduleSlot(
                id=7,
                item_id=5,
                date=tomorrow,
                start_time=time(9, 0),
                end_time=time(12, 0),
                capacity=5,
            )
        )
        session.add(
            ScheduleSlot(
                id=8,
                item_id=2,
                date=yesterday,
                start_time=time(9, 0),
                end_time=time(12, 0),
                capacity=5,
            )
        )
        await session.commit()
    return Seed(
        user_a_id=1,
        user_b_id=2,
        item_id=2,
        inactive_item_id=5,
        slot_id=3,
        other_item_slot_id=7,
        past_slot_id=8,
        address_a_id=4,
        address_b_id=6,
        capacity=5,
        base_price=Decimal("100.00"),
    )


@pytest.mark.integration
async def test_place_order_returns_201_with_summary(api_client, seeded) -> None:
    """合法请求 -> 201 + 订单摘要，且只回摘要字段。"""
    response = await api_client.post(
        ORDER_URL,
        json=_valid_body(seeded),
        headers=_auth_header(seeded.user_a_id),
    )
    assert response.status_code == 201
    body = response.json()
    # 摘要恰好四个字段：内部字段（provider_id / master_id）和地址都不往外发
    assert set(body) == {"id", "order_no", "status", "amount"}
    assert body["status"] == OrderStatus.PENDING_PAY.value
    assert body["order_no"].startswith("OTO")
    assert Decimal(str(body["amount"])) == seeded.base_price


@pytest.mark.integration
async def test_order_user_id_comes_from_token(api_client, seeded, db) -> None:
    """订单的 user_id 来自 token，不是请求体。

    请求体里根本没有 user_id 这个位置（带了就是 422），
    所以落库的 user_id 只能是 token 里的那个。
    """
    response = await api_client.post(
        ORDER_URL,
        json={
            "item_id": seeded.item_id,
            "slot_id": seeded.slot_id,
            "address_id": seeded.address_b_id,
        },
        headers=_auth_header(seeded.user_b_id),
    )
    assert response.status_code == 201

    maker = async_sessionmaker(db, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        order = (await session.execute(select(Order))).scalar_one()
        assert order.user_id == seeded.user_b_id  # token 里的用户
        assert order.address_id == seeded.address_b_id  # 请求里的地址
        assert order.amount == seeded.base_price


@pytest.mark.integration
async def test_address_of_other_user_returns_404(api_client, seeded) -> None:
    """用户 A 的 token + 用户 B 的地址 -> 404（不是 403，不暴露存在性）。"""
    response = await api_client.post(
        ORDER_URL,
        json={
            "item_id": seeded.item_id,
            "slot_id": seeded.slot_id,
            "address_id": seeded.address_b_id,
        },
        headers=_auth_header(seeded.user_a_id),
    )
    assert response.status_code == 404
    assert "detail" in response.json()


@pytest.mark.integration
async def test_missing_address_returns_same_404_detail(api_client, seeded) -> None:
    """地址根本不存在 -> 404，且与「地址属于别人」的错误文案同一模板。

    文案模板一致（只有回显的 id 不同）= 调用方没法靠错误差异
    探测某个地址是否存在。
    """
    other_user = await api_client.post(
        ORDER_URL,
        json={
            "item_id": seeded.item_id,
            "slot_id": seeded.slot_id,
            "address_id": seeded.address_b_id,
        },
        headers=_auth_header(seeded.user_a_id),
    )
    missing = await api_client.post(
        ORDER_URL,
        json={
            "item_id": seeded.item_id,
            "slot_id": seeded.slot_id,
            "address_id": 999999,
        },
        headers=_auth_header(seeded.user_a_id),
    )
    assert other_user.status_code == 404
    assert missing.status_code == 404
    # 数字换成占位符后应当完全一致：不存在与「不属于你」说的是同一句话
    template = re.compile(r"\d+")
    assert template.sub("#", other_user.json()["detail"]) == template.sub(
        "#", missing.json()["detail"]
    )
    # 文案里不得出现归属信息（否则等于承认地址存在）
    for detail in (other_user.json()["detail"], missing.json()["detail"]):
        assert "user" not in detail.lower()
        assert "用户" not in detail


@pytest.mark.integration
async def test_slot_not_reservable_returns_409(api_client, seeded, db) -> None:
    """库存不足 -> 409。"""
    maker = async_sessionmaker(db, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        await session.execute(
            update(ScheduleSlot)
            .where(ScheduleSlot.id == seeded.slot_id)
            .values(used=seeded.capacity)
        )
        await session.commit()

    response = await api_client.post(
        ORDER_URL,
        json=_valid_body(seeded),
        headers=_auth_header(seeded.user_a_id),
    )
    assert response.status_code == 409


@pytest.mark.integration
async def test_inactive_item_returns_409(api_client, seeded) -> None:
    """服务项已停用 -> 409。"""
    response = await api_client.post(
        ORDER_URL,
        json={
            "item_id": seeded.inactive_item_id,
            "slot_id": seeded.other_item_slot_id,
            "address_id": seeded.address_a_id,
        },
        headers=_auth_header(seeded.user_a_id),
    )
    assert response.status_code == 409


@pytest.mark.integration
async def test_missing_item_returns_404(api_client, seeded) -> None:
    """服务项不存在 -> 404。"""
    response = await api_client.post(
        ORDER_URL,
        json={
            "item_id": 999999,
            "slot_id": seeded.slot_id,
            "address_id": seeded.address_a_id,
        },
        headers=_auth_header(seeded.user_a_id),
    )
    assert response.status_code == 404


@pytest.mark.integration
async def test_missing_slot_returns_404(api_client, seeded) -> None:
    """时段不存在 -> 404。"""
    response = await api_client.post(
        ORDER_URL,
        json={
            "item_id": seeded.item_id,
            "slot_id": 999999,
            "address_id": seeded.address_a_id,
        },
        headers=_auth_header(seeded.user_a_id),
    )
    assert response.status_code == 404


@pytest.mark.integration
async def test_slot_item_mismatch_returns_409(api_client, seeded) -> None:
    """时段不属于所选服务项 -> 409。"""
    response = await api_client.post(
        ORDER_URL,
        json={
            "item_id": seeded.item_id,
            "slot_id": seeded.other_item_slot_id,
            "address_id": seeded.address_a_id,
        },
        headers=_auth_header(seeded.user_a_id),
    )
    assert response.status_code == 409


@pytest.mark.integration
async def test_slot_in_past_returns_409(api_client, seeded) -> None:
    """时段不在将来 -> 409。"""
    response = await api_client.post(
        ORDER_URL,
        json={
            "item_id": seeded.item_id,
            "slot_id": seeded.past_slot_id,
            "address_id": seeded.address_a_id,
        },
        headers=_auth_header(seeded.user_a_id),
    )
    assert response.status_code == 409
