"""收货地址接口的测试（列表 / 新建 / 修改 / 删除）。

必测点：

1. **A 改 / 删 B 的地址 -> 404，且与「地址根本不存在」的响应完全一样**
   （404 同构，R5）：调用方不能靠错误差异探测别人的地址存不存在。
2. **地址列表只返回自己的**（R5）。
3. **归属不可伪造**：请求体里带 user_id -> 422（身份只从 token 来，R1）。

集成测试用的数据库是 TEST_DATABASE_URL 指向的独立测试库
（集成 fixture 每次 drop_all + create_all，绝不碰开发库）。
"""
from __future__ import annotations

import os
import re
from datetime import date, time, timedelta
from decimal import Decimal

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from tests.support import business_today
from app.core.auth import create_access_token
from app.core.database import get_session
from app.main import app
from app.models.address import Address
from app.models.base import Base
from app.models.catalog import ServiceCategory, ServiceItem
from app.models.enums import OrderStatus, PayStatus, UserRole
from app.models.order import Order
from app.models.schedule_slot import ScheduleSlot
from app.models.user import User

ADDRESSES_URL = "/api/v1/addresses"
ORDERS_URL = "/api/v1/orders"

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

# 用来对比「不是我的」与「根本不存在」两个 404 的文案模板
DIGITS = re.compile(r"\d+")


def _auth_header(user_id: int, **kwargs) -> dict[str, str]:
    """生成带合法 token 的请求头（默认普通 C 端用户身份）。"""
    kwargs.setdefault("role", UserRole.USER)
    kwargs.setdefault("provider_id", None)
    token = create_access_token(user_id, **kwargs)
    return {"Authorization": "Bearer {}".format(token)}


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


@pytest.fixture
async def seeded(db) -> dict[str, int]:
    """两个用户，每人一条地址。

    **不显式指定 id**：让数据库序列自己分配。显式写 id（比如 id=30）会让序列
    停在 1，后面服务新建的地址拿到 id=1，跟「排序按 id 升序」之类的假设对不上，
    也可能撞上已存在的行。id 一律从落库对象上取。
    """
    maker = async_sessionmaker(db, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        user_a = User(phone="13800000001")
        user_b = User(phone="13800000002")
        session.add_all([user_a, user_b])
        await session.flush()

        address_a = Address(
            user_id=user_a.id,
            contact="张三",
            phone="13800000001",
            region="北京",
            detail="某街道 1 号",
        )
        address_b = Address(
            user_id=user_b.id,
            contact="李四",
            phone="13800000002",
            region="上海",
            detail="某路 2 号",
        )
        session.add_all([address_a, address_b])
        await session.flush()
        await session.commit()
        return {
            "user_a": user_a.id,
            "user_b": user_b.id,
            "address_a": address_a.id,
            "address_b": address_b.id,
        }


PAYLOAD = {
    "contact": "王五",
    "phone": "13800000003",
    "region": "广东 深圳",
    "detail": "科技园 5 号楼 301",
}


# =====================================================================
# 列表
# =====================================================================


@pytest.mark.integration
async def test_address_list_only_returns_my_addresses(api_client, seeded) -> None:
    """A 的列表里只有 A 那条地址（R5）。"""
    response = await api_client.get(
        ADDRESSES_URL, headers=_auth_header(seeded["user_a"])
    )
    assert response.status_code == 200
    body = response.json()
    assert [item["id"] for item in body] == [seeded["address_a"]]
    assert body[0]["contact"] == "张三"
    # 归属字段不外发
    assert "user_id" not in body[0]


# =====================================================================
# 新建
# =====================================================================


@pytest.mark.integration
async def test_create_address_returns_201_and_shows_up_in_list(
    api_client, seeded
) -> None:
    """新建的地址出现在自己的列表里。"""
    headers = _auth_header(seeded["user_a"])
    created = await api_client.post(ADDRESSES_URL, json=PAYLOAD, headers=headers)
    assert created.status_code == 201
    body = created.json()
    assert body["contact"] == "王五"
    assert body["region"] == "广东 深圳"
    assert body["detail"] == "科技园 5 号楼 301"
    assert body["id"] > 0

    listed = await api_client.get(ADDRESSES_URL, headers=headers)
    assert [item["id"] for item in listed.json()] == [
        seeded["address_a"],
        body["id"],
    ]


@pytest.mark.integration
async def test_create_address_rejects_user_id_in_body(api_client, seeded) -> None:
    """请求体里带 user_id -> 422：归属只从 token 来（R1）。"""
    response = await api_client.post(
        ADDRESSES_URL,
        json={**PAYLOAD, "user_id": seeded["user_b"]},
        headers=_auth_header(seeded["user_a"]),
    )
    assert response.status_code == 422


# =====================================================================
# 必测 1：A 改 / 删 B 的地址 -> 404 同构
# =====================================================================


@pytest.mark.integration
async def test_update_other_users_address_returns_404(api_client, seeded) -> None:
    """A 改 B 的地址 -> 404。"""
    response = await api_client.put(
        "{}/{}".format(ADDRESSES_URL, seeded["address_b"]),
        json=PAYLOAD,
        headers=_auth_header(seeded["user_a"]),
    )
    assert response.status_code == 404


@pytest.mark.integration
async def test_delete_other_users_address_returns_404(api_client, seeded) -> None:
    """A 删 B 的地址 -> 404。"""
    response = await api_client.delete(
        "{}/{}".format(ADDRESSES_URL, seeded["address_b"]),
        headers=_auth_header(seeded["user_a"]),
    )
    assert response.status_code == 404


@pytest.mark.integration
async def test_update_other_users_address_is_isomorphic_to_missing(
    api_client, seeded
) -> None:
    """「不是我的」与「根本不存在」返回**完全一样**的 404。

    文案模板一致（数字换成占位符后逐字相同）= 调用方没法靠错误差异
    探测某个地址存不存在、归谁。
    """
    not_mine = await api_client.put(
        "{}/{}".format(ADDRESSES_URL, seeded["address_b"]),
        json=PAYLOAD,
        headers=_auth_header(seeded["user_a"]),
    )
    missing = await api_client.put(
        "{}/999999".format(ADDRESSES_URL),
        json=PAYLOAD,
        headers=_auth_header(seeded["user_a"]),
    )
    assert not_mine.status_code == 404
    assert missing.status_code == 404
    assert DIGITS.sub("#", not_mine.json()["detail"]) == DIGITS.sub(
        "#", missing.json()["detail"]
    )
    # 文案里不得出现归属信息
    for detail in (not_mine.json()["detail"], missing.json()["detail"]):
        assert "user" not in detail.lower()
        assert "用户" not in detail


@pytest.mark.integration
async def test_delete_other_users_address_is_isomorphic_to_missing(
    api_client, seeded
) -> None:
    """删地址时同样 404 同构。"""
    not_mine = await api_client.delete(
        "{}/{}".format(ADDRESSES_URL, seeded["address_b"]),
        headers=_auth_header(seeded["user_a"]),
    )
    missing = await api_client.delete(
        "{}/999999".format(ADDRESSES_URL),
        headers=_auth_header(seeded["user_a"]),
    )
    assert not_mine.status_code == 404
    assert missing.status_code == 404
    assert DIGITS.sub("#", not_mine.json()["detail"]) == DIGITS.sub(
        "#", missing.json()["detail"]
    )


@pytest.mark.integration
async def test_other_users_address_is_untouched(api_client, seeded) -> None:
    """越权改 / 删之后，B 的地址内容一点没变。"""
    headers = _auth_header(seeded["user_b"])
    await api_client.put(
        "{}/{}".format(ADDRESSES_URL, seeded["address_b"]),
        json=PAYLOAD,
        headers=_auth_header(seeded["user_a"]),
    )
    await api_client.delete(
        "{}/{}".format(ADDRESSES_URL, seeded["address_b"]),
        headers=_auth_header(seeded["user_a"]),
    )
    listed = await api_client.get(ADDRESSES_URL, headers=headers)
    body = listed.json()
    assert len(body) == 1
    assert body[0]["contact"] == "李四"
    assert body[0]["region"] == "上海"


# =====================================================================
# 改自己的 / 删自己的
# =====================================================================


@pytest.mark.integration
async def test_update_my_address_changes_fields(api_client, seeded) -> None:
    """改自己的地址 -> 200，字段确实变了。"""
    response = await api_client.put(
        "{}/{}".format(ADDRESSES_URL, seeded["address_a"]),
        json={**PAYLOAD, "contact": "赵六"},
        headers=_auth_header(seeded["user_a"]),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == seeded["address_a"]
    assert body["contact"] == "赵六"
    assert body["region"] == "广东 深圳"

    listed = await api_client.get(
        ADDRESSES_URL, headers=_auth_header(seeded["user_a"])
    )
    assert listed.json()[0]["contact"] == "赵六"


@pytest.mark.integration
async def test_delete_my_address_removes_it_from_list(api_client, seeded) -> None:
    """删自己的地址 -> 204，列表里没有了。"""
    response = await api_client.delete(
        "{}/{}".format(ADDRESSES_URL, seeded["address_a"]),
        headers=_auth_header(seeded["user_a"]),
    )
    assert response.status_code == 204
    assert response.content == b""

    listed = await api_client.get(
        ADDRESSES_URL, headers=_auth_header(seeded["user_a"])
    )
    assert listed.json() == []


# =====================================================================
# 地址被订单引用 -> 409（不是 500）
# =====================================================================


async def _create_order_for_address(
    db, *, user_id: int, address_id: int
) -> str:
    """造一笔引用该地址的订单（连同品类 / 服务项 / 时段）。

    订单表的 address_id 上是 RESTRICT 外键：地址一旦被订单引用就删不掉。
    """
    maker = async_sessionmaker(db, class_=AsyncSession, expire_on_commit=False)
    tomorrow = business_today() + timedelta(days=1)
    async with maker() as session:
        category = ServiceCategory(name="家庭保洁", parent_id=None, sort_order=1)
        session.add(category)
        await session.flush()

        item = ServiceItem(
            category_id=category.id,
            name="日常保洁",
            base_price=Decimal("100.00"),
            duration_min=60,
        )
        session.add(item)
        await session.flush()

        slot = ScheduleSlot(
            item_id=item.id,
            date=tomorrow,
            start_time=time(9, 0),
            end_time=time(11, 0),
            capacity=5,
            used=0,
        )
        session.add(slot)
        await session.flush()

        order = Order(
            order_no="OTO20260101007777",
            user_id=user_id,
            provider_id=None,
            master_id=None,
            address_id=address_id,
            item_id=item.id,
            slot_id=slot.id,
            amount=Decimal("100.00"),
            status=OrderStatus.PENDING_PAY,
            pay_status=PayStatus.UNPAID,
        )
        session.add(order)
        await session.commit()
        return order.order_no


@pytest.mark.integration
async def test_delete_address_used_by_order_returns_409(
    api_client, seeded, db
) -> None:
    """地址被订单引用时删除 -> 409，地址和订单都还在。

    409 而不是 500：外键冲突是「换个地址 / 先处理订单」能解决的冲突，
    不是服务端坏了。
    """
    order_no = await _create_order_for_address(
        db, user_id=seeded["user_a"], address_id=seeded["address_a"]
    )
    headers = _auth_header(seeded["user_a"])

    response = await api_client.delete(
        "{}/{}".format(ADDRESSES_URL, seeded["address_a"]), headers=headers
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "地址已被订单使用，无法删除"

    # 地址还在
    listed = await api_client.get(ADDRESSES_URL, headers=headers)
    assert seeded["address_a"] in [item["id"] for item in listed.json()]

    # 订单也还在
    orders = await api_client.get(ORDERS_URL, headers=headers)
    assert order_no in [item["order_no"] for item in orders.json()["items"]]


# =====================================================================
# 鉴权
# =====================================================================


@pytest.mark.integration
async def test_addresses_require_authentication(api_client, seeded) -> None:
    """没有 token 的地址接口一律 401。"""
    cases = [
        ("GET", ADDRESSES_URL, None),
        ("POST", ADDRESSES_URL, PAYLOAD),
        ("PUT", "{}/{}".format(ADDRESSES_URL, seeded["address_a"]), PAYLOAD),
        ("DELETE", "{}/{}".format(ADDRESSES_URL, seeded["address_a"]), None),
    ]
    for method, url, payload in cases:
        response = await api_client.request(method, url, json=payload)
        assert response.status_code == 401, url
        assert response.json() == {"detail": "Unauthorized"}
