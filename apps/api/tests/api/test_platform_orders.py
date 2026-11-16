"""平台侧订单总览接口的测试（/api/v1/platform/orders）。

必测点：

1. **鉴权**：不是平台侧角色（普通用户 / 服务商账号）-> 403；
   没 token -> 401；PLATFORM_OPS 能进（平台运营也看得到总览）。
2. **平台看全量**：订单**不按用户过滤**，也不按服务商过滤——
   跨服务商的数据全可见（这是平台侧的特权，来自角色，不是来自参数）。
3. **能按 provider_id / status 筛选**：筛选是查询条件，不是隔离边界。
4. **分页**：page / limit / total 对得上；limit 上限 100（超过按 100 算）。

集成测试用的数据库是 TEST_DATABASE_URL 指向的独立测试库
（集成 fixture 每次 drop_all + create_all，绝不碰开发库）。
"""
from __future__ import annotations

import os
from datetime import time, timedelta
from decimal import Decimal

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.auth import create_access_token
from app.core.database import get_session
from app.main import app
from app.models.address import Address
from app.models.base import Base
from app.models.catalog import ServiceCategory, ServiceItem
from app.models.enums import OrderStatus, PayStatus, UserRole
from app.models.order import Order
from app.models.provider import ServiceProvider
from app.models.schedule_slot import ScheduleSlot
from app.models.user import User
from tests.support import business_today

ORDERS_URL = "/api/v1/platform/orders"

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


def _auth_header(user_id: int, role: UserRole, provider_id: int | None) -> dict[str, str]:
    token = create_access_token(user_id, role, provider_id)
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


async def _seed(db) -> dict[str, int]:
    """造平台账号、服务商账号、两个服务商，以及分属不同服务商的若干订单。

    **不显式指定 id**：让数据库序列自己分配（显式写 id 会让序列停在 1，
    后面服务新建的行拿到 id=1 撞车）。
    """
    maker = async_sessionmaker(db, class_=AsyncSession, expire_on_commit=False)
    tomorrow = business_today() + timedelta(days=1)

    async with maker() as session:
        platform_admin = User(
            phone="13700000001",
            nickname="平台管理员",
            role=UserRole.PLATFORM_ADMIN,
            provider_id=None,
        )
        platform_ops = User(
            phone="13700000002",
            nickname="平台运营",
            role=UserRole.PLATFORM_OPS,
            provider_id=None,
        )
        plain_user = User(phone="13700000003", nickname="普通用户")
        customer = User(phone="13800000004", nickname="客户")
        session.add_all([platform_admin, platform_ops, plain_user, customer])
        await session.flush()

        provider_a = ServiceProvider(name="甲服务商", contact_phone="13900000001")
        provider_b = ServiceProvider(name="乙服务商", contact_phone="13900000002")
        session.add_all([provider_a, provider_b])
        await session.flush()

        # 服务商账号必须带 provider_id（数据库 CHECK 约束强制）
        provider_admin = User(
            phone="13800000005",
            nickname="服务商管理员",
            role=UserRole.PROVIDER_ADMIN,
            provider_id=provider_a.id,
        )
        session.add(provider_admin)
        await session.flush()

        address = Address(
            user_id=customer.id,
            contact="客户",
            phone="13800000004",
            region="北京",
            detail="某街道 1 号",
        )
        session.add(address)
        await session.flush()

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

        def _order(
            order_no: str,
            status: OrderStatus,
            *,
            provider_id: int | None = None,
            amount: str = "100.00",
            pay_status: PayStatus = PayStatus.PAID,
        ) -> Order:
            return Order(
                order_no=order_no,
                user_id=customer.id,
                provider_id=provider_id,
                master_id=None,
                address_id=address.id,
                item_id=item.id,
                slot_id=slot.id,
                amount=Decimal(amount),
                status=status,
                pay_status=pay_status,
            )

        # 甲服务商的单
        order_a = _order(
            "OTO20260101000001", OrderStatus.IN_SERVICE, provider_id=provider_a.id
        )
        # 乙服务商的单（跨商数据：平台必须看得见）
        order_b = _order(
            "OTO20260101000002", OrderStatus.COMPLETED, provider_id=provider_b.id
        )
        # 还没派出去的单：provider_id 为空，平台同样看得见
        order_open = _order("OTO20260101000003", OrderStatus.PENDING_DISPATCH)
        session.add_all([order_a, order_b, order_open])
        await session.flush()
        await session.commit()

        return {
            "platform_admin": platform_admin.id,
            "platform_ops": platform_ops.id,
            "plain_user": plain_user.id,
            "provider_admin": provider_admin.id,
            "customer": customer.id,
            "provider_a": provider_a.id,
            "provider_b": provider_b.id,
            "order_a": order_a.id,
            "order_b": order_b.id,
            "order_open": order_open.id,
        }


@pytest.fixture
async def seeded(db) -> dict[str, int]:
    return await _seed(db)


def _platform_headers(seeded: dict[str, int]) -> dict[str, str]:
    return _auth_header(seeded["platform_admin"], UserRole.PLATFORM_ADMIN, None)


# =====================================================================
# 鉴权
# =====================================================================


@pytest.mark.integration
async def test_list_orders_requires_authentication(api_client, seeded) -> None:
    """没有 token -> 401。"""
    response = await api_client.get(ORDERS_URL)
    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}


@pytest.mark.integration
async def test_list_orders_rejects_plain_user(api_client, seeded) -> None:
    """普通用户 -> 403。"""
    headers = _auth_header(seeded["plain_user"], UserRole.USER, None)
    response = await api_client.get(ORDERS_URL, headers=headers)
    assert response.status_code == 403
    assert response.json() == {"detail": "Forbidden"}


@pytest.mark.integration
async def test_list_orders_rejects_provider_admin(api_client, seeded) -> None:
    """服务商账号 -> 403：平台侧接口与服务商侧不是一回事。"""
    headers = _auth_header(
        seeded["provider_admin"], UserRole.PROVIDER_ADMIN, seeded["provider_a"]
    )
    response = await api_client.get(ORDERS_URL, headers=headers)
    assert response.status_code == 403


@pytest.mark.integration
async def test_list_orders_allows_platform_ops(api_client, seeded) -> None:
    """平台运营（PLATFORM_OPS）也能看订单总览。"""
    headers = _auth_header(seeded["platform_ops"], UserRole.PLATFORM_OPS, None)
    response = await api_client.get(ORDERS_URL, headers=headers)
    assert response.status_code == 200
    assert response.json()["total"] == 3


# =====================================================================
# 平台特权：看全量
# =====================================================================


@pytest.mark.integration
async def test_list_orders_returns_all_orders_across_providers(api_client, seeded) -> None:
    """不筛选 -> 全量订单（含两家服务商的与还没派的）。

    这是平台侧的特权：订单不按用户过滤，也不按服务商过滤。
    """
    headers = _platform_headers(seeded)
    response = await api_client.get(ORDERS_URL, headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    order_nos = {item["order_no"] for item in body["items"]}
    assert order_nos == {
        "OTO20260101000001",
        "OTO20260101000002",
        "OTO20260101000003",
    }


@pytest.mark.integration
async def test_list_orders_shows_provider_name_and_item(api_client, seeded) -> None:
    """列表里带得出服务商名与服务项名（还没派的单服务商名为空）。"""
    headers = _platform_headers(seeded)
    response = await api_client.get(ORDERS_URL, headers=headers)
    assert response.status_code == 200
    by_no = {item["order_no"]: item for item in response.json()["items"]}

    assert by_no["OTO20260101000001"]["provider_name"] == "甲服务商"
    assert by_no["OTO20260101000002"]["provider_name"] == "乙服务商"
    assert by_no["OTO20260101000003"]["provider_name"] is None
    assert by_no["OTO20260101000001"]["item_name"] == "日常保洁"
    assert by_no["OTO20260101000001"]["user_id"] == seeded["customer"]


@pytest.mark.integration
async def test_list_orders_includes_provider_filter_options(api_client, seeded) -> None:
    """筛选栏的服务商选项：有过订单的服务商都在（按 id 排序）。

    平台运营也要能按服务商筛，而平台侧的服务商列表接口只对平台管理员开放，
    所以订单接口自己带上筛选选项。
    """
    headers = _platform_headers(seeded)
    response = await api_client.get(ORDERS_URL, headers=headers)
    assert response.status_code == 200
    providers = response.json()["providers"]
    assert providers == [
        {"id": seeded["provider_a"], "name": "甲服务商"},
        {"id": seeded["provider_b"], "name": "乙服务商"},
    ]


# =====================================================================
# 筛选
# =====================================================================


@pytest.mark.integration
async def test_list_orders_filters_by_provider(api_client, seeded) -> None:
    """按 provider_id 筛选：只出这一家的单。"""
    headers = _platform_headers(seeded)
    response = await api_client.get(
        ORDERS_URL,
        params={"provider_id": seeded["provider_a"]},
        headers=headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["order_no"] == "OTO20260101000001"
    assert body["items"][0]["provider_id"] == seeded["provider_a"]


@pytest.mark.integration
async def test_list_orders_filters_by_status(api_client, seeded) -> None:
    """按状态筛选。"""
    headers = _platform_headers(seeded)
    response = await api_client.get(
        ORDERS_URL, params={"status": "COMPLETED"}, headers=headers
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["status"] == "COMPLETED"


@pytest.mark.integration
async def test_list_orders_filters_combine(api_client, seeded) -> None:
    """状态 + 服务商一起筛：条件是「与」的关系。"""
    headers = _platform_headers(seeded)
    response = await api_client.get(
        ORDERS_URL,
        params={"status": "COMPLETED", "provider_id": seeded["provider_a"]},
        headers=headers,
    )
    assert response.status_code == 200
    # 甲服务商的单是服务中，不是已完成 -> 交集为空
    assert response.json()["total"] == 0


# =====================================================================
# 分页
# =====================================================================


@pytest.mark.integration
async def test_list_orders_pages(api_client, seeded) -> None:
    """分页：page=2 只剩下一页的条目，total 不受分页影响。"""
    headers = _platform_headers(seeded)
    response = await api_client.get(
        ORDERS_URL, params={"page": 2, "limit": 2}, headers=headers
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert body["page"] == 2
    assert body["limit"] == 2
    assert len(body["items"]) == 1


@pytest.mark.integration
async def test_list_orders_clamps_limit_to_100(api_client, seeded) -> None:
    """分页上限 100：传 500 时按 100 算（不报错），回显收敛后的值。"""
    headers = _platform_headers(seeded)
    response = await api_client.get(
        ORDERS_URL, params={"limit": 500}, headers=headers
    )
    assert response.status_code == 200
    assert response.json()["limit"] == 100


@pytest.mark.integration
async def test_list_orders_rejects_zero_limit(api_client, seeded) -> None:
    """limit 必须 >= 1 -> 422（接口层就挡住，不进 service）。"""
    headers = _platform_headers(seeded)
    response = await api_client.get(
        ORDERS_URL, params={"limit": 0}, headers=headers
    )
    assert response.status_code == 422
