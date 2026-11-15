"""服务商侧只读查询接口的测试（待派单列表 / 本商师傅列表）。

必测点：

1. **可见范围 = 能派的范围**：待派单列表里出现公共池（还没归属）的单与
   本商拒单退回的单，**不出现**别家的单；
2. **师傅列表只返回本商的**（R5）：别家师傅不出现；
3. **归属不可伪造**：请求里带 provider_id 不起作用（接口压根没这个入参）;
4. **鉴权**：没 token -> 401；不是服务商侧角色 -> 403。

集成测试用的数据库是 TEST_DATABASE_URL 指向的独立测试库
（集成 fixture 每次 drop_all + create_all，绝不碰开发库）。
"""
from __future__ import annotations

import os
from datetime import date, time, timedelta
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
from app.models.enums import (
    MasterStatus,
    OrderStatus,
    PayStatus,
    UserRole,
)
from app.models.order import Order
from app.models.provider import Master, ServiceProvider
from app.models.schedule_slot import ScheduleSlot
from app.models.user import User

ORDERS_URL = "/api/v1/provider/orders"
MASTERS_URL = "/api/v1/provider/masters"

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
    """造两个服务商、各自的师傅与若干状态的订单。

    **不显式指定 id**：让数据库序列自己分配。显式写 id 会让序列停在 1，
    后面服务新建的行拿到 id=1，跟已存在的行撞车。id 一律从落库对象上取。
    """
    maker = async_sessionmaker(db, class_=AsyncSession, expire_on_commit=False)
    tomorrow = date.today() + timedelta(days=1)

    async with maker() as session:
        provider_a = ServiceProvider(name="甲服务商", contact_phone="13900000001")
        provider_b = ServiceProvider(name="乙服务商", contact_phone="13900000002")
        session.add_all([provider_a, provider_b])
        await session.flush()

        admin_a = User(
            phone="13800000001",
            nickname="甲管理员",
            role=UserRole.PROVIDER_ADMIN,
            provider_id=provider_a.id,
        )
        admin_b = User(
            phone="13800000002",
            nickname="乙管理员",
            role=UserRole.PROVIDER_ADMIN,
            provider_id=provider_b.id,
        )
        plain_user = User(phone="13800000003", nickname="普通用户")
        customer = User(phone="13800000004", nickname="客户")
        # 每个师傅一个独立账号：master.user_id 上有唯一约束
        # （uq_master_user_id），一个登录用户最多对应一个师傅身份
        master_user_a1 = User(phone="13800000005", nickname="师傅甲一账号")
        master_user_a2 = User(phone="13800000006", nickname="师傅甲二账号")
        master_user_b1 = User(phone="13800000007", nickname="师傅乙一账号")
        session.add_all(
            [admin_a, admin_b, plain_user, customer, master_user_a1, master_user_a2, master_user_b1]
        )
        await session.flush()

        master_a1 = Master(
            provider_id=provider_a.id,
            user_id=master_user_a1.id,
            real_name="师傅甲一",
            status=MasterStatus.ACTIVE,
            rating=Decimal("4.5"),
        )
        master_a2 = Master(
            provider_id=provider_a.id,
            user_id=master_user_a2.id,
            real_name="师傅甲二",
            status=MasterStatus.PENDING,
            rating=None,
        )
        master_b1 = Master(
            provider_id=provider_b.id,
            user_id=master_user_b1.id,
            real_name="师傅乙一",
            status=MasterStatus.ACTIVE,
            rating=Decimal("4.0"),
        )
        session.add_all([master_a1, master_a2, master_b1])
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
            master_id: int | None = None,
            amount: str = "100.00",
            pay_status: PayStatus = PayStatus.PAID,
        ) -> Order:
            return Order(
                order_no=order_no,
                user_id=customer.id,
                provider_id=provider_id,
                master_id=master_id,
                address_id=address.id,
                item_id=item.id,
                slot_id=slot.id,
                amount=Decimal(amount),
                status=status,
                pay_status=pay_status,
            )

        # 公共待派单池：还没归属，任何服务商都能派
        open_order = _order("OTO20260101000001", OrderStatus.PENDING_DISPATCH)
        # 本商拒单退回：归属是甲、当前没有承接人
        own_rejected = _order(
            "OTO20260101000002",
            OrderStatus.PENDING_DISPATCH,
            provider_id=provider_a.id,
        )
        # 别家的单：乙服务商专属，甲不该看见
        foreign_order = _order(
            "OTO20260101000003",
            OrderStatus.PENDING_DISPATCH,
            provider_id=provider_b.id,
        )
        # 已经派给甲的师傅（待接单）
        dispatched = _order(
            "OTO20260101000004",
            OrderStatus.PENDING_ACCEPT,
            provider_id=provider_a.id,
            master_id=master_a1.id,
        )
        # 还没付款：provider_id 为空，但状态不是待派单
        unpaid = _order(
            "OTO20260101000005",
            OrderStatus.PENDING_PAY,
            pay_status=PayStatus.UNPAID,
        )
        session.add_all([open_order, own_rejected, foreign_order, dispatched, unpaid])
        await session.flush()
        await session.commit()

        return {
            "provider_a": provider_a.id,
            "provider_b": provider_b.id,
            "admin_a": admin_a.id,
            "admin_b": admin_b.id,
            "plain_user": plain_user.id,
            "master_a1": master_a1.id,
            "master_a2": master_a2.id,
            "master_b1": master_b1.id,
            "open_order": open_order.id,
            "own_rejected": own_rejected.id,
            "foreign_order": foreign_order.id,
            "dispatched": dispatched.id,
            "unpaid": unpaid.id,
        }


@pytest.fixture
async def seeded(db) -> dict[str, int]:
    return await _seed(db)


def _admin_a_headers(seeded: dict[str, int]) -> dict[str, str]:
    return _auth_header(seeded["admin_a"], UserRole.PROVIDER_ADMIN, seeded["provider_a"])


# =====================================================================
# 待派单列表
# =====================================================================


@pytest.mark.integration
async def test_pending_dispatch_list_shows_dispatchable_orders(
    api_client, seeded
) -> None:
    """待派单列表 = 公共池 + 本商拒单退回，别家的单不出现。"""
    response = await api_client.get(
        ORDERS_URL, params={"status": "PENDING_DISPATCH"}, headers=_admin_a_headers(seeded)
    )
    assert response.status_code == 200
    body = response.json()

    order_ids = {item["id"] for item in body["items"]}
    assert seeded["open_order"] in order_ids
    assert seeded["own_rejected"] in order_ids
    # 别人的单不能出现
    assert seeded["foreign_order"] not in order_ids
    # 别的状态也不能出现
    assert seeded["dispatched"] not in order_ids
    assert seeded["unpaid"] not in order_ids
    assert body["total"] == 2


@pytest.mark.integration
async def test_pending_dispatch_list_defaults_to_pending_dispatch(
    api_client, seeded
) -> None:
    """不传 status 时默认就是待派单。"""
    response = await api_client.get(ORDERS_URL, headers=_admin_a_headers(seeded))
    assert response.status_code == 200
    order_ids = {item["id"] for item in response.json()["items"]}
    assert order_ids == {seeded["open_order"], seeded["own_rejected"]}


@pytest.mark.integration
async def test_provider_order_list_items_carry_dispatch_fields(
    api_client, seeded
) -> None:
    """列表项带上前端拼派单 URL 需要的数字 id 与订单号。"""
    response = await api_client.get(
        ORDERS_URL, headers=_admin_a_headers(seeded)
    )
    assert response.status_code == 200
    item = next(
        row for row in response.json()["items"] if row["id"] == seeded["open_order"]
    )
    assert item["order_no"] == "OTO20260101000001"
    assert item["item_name"] == "日常保洁"
    assert item["status"] == "PENDING_DISPATCH"
    assert item["amount"] == "100.00"
    assert item["created_at"]


@pytest.mark.integration
async def test_other_provider_cannot_see_foreign_pending_orders(
    api_client, seeded
) -> None:
    """乙服务商看到公共池 + 自己的那笔，看不到甲专属的那笔。

    公共池（provider_id 为空）对每个服务商都可见——这正是「还没人接的单，
    谁都能派」的意思；甲拒单退回的单是甲专属的，乙不该看见。
    """
    headers = _auth_header(
        seeded["admin_b"], UserRole.PROVIDER_ADMIN, seeded["provider_b"]
    )
    response = await api_client.get(ORDERS_URL, headers=headers)
    assert response.status_code == 200
    order_ids = {item["id"] for item in response.json()["items"]}
    assert order_ids == {seeded["open_order"], seeded["foreign_order"]}
    assert seeded["own_rejected"] not in order_ids


@pytest.mark.integration
async def test_provider_order_list_ignores_client_supplied_provider_id(
    api_client, seeded
) -> None:
    """请求里带 provider_id 不起作用：接口压根没这个入参。

    客户端自报归属等于让它自己挑租户——这里验证它挑不动：
    甲的管理员就算在 query 里写上乙的 provider_id，看到的仍然是甲的数据。
    """
    headers = _admin_a_headers(seeded)
    without = await api_client.get(ORDERS_URL, headers=headers)
    with_param = await api_client.get(
        ORDERS_URL,
        params={"provider_id": seeded["provider_b"]},
        headers=headers,
    )
    assert with_param.status_code == 200
    assert with_param.json() == without.json()


@pytest.mark.integration
async def test_provider_order_list_paginates(api_client, seeded) -> None:
    """分页：limit / offset 生效，total 不受分页影响。"""
    headers = _admin_a_headers(seeded)
    page = await api_client.get(
        ORDERS_URL, params={"limit": 1, "offset": 0}, headers=headers
    )
    assert page.status_code == 200
    body = page.json()
    assert len(body["items"]) == 1
    assert body["total"] == 2
    assert body["limit"] == 1
    assert body["offset"] == 0


# =====================================================================
# 师傅列表
# =====================================================================


@pytest.mark.integration
async def test_master_list_only_returns_own_provider_masters(
    api_client, seeded
) -> None:
    """师傅列表只含本商师傅。"""
    response = await api_client.get(MASTERS_URL, headers=_admin_a_headers(seeded))
    assert response.status_code == 200
    body = response.json()
    master_ids = {item["id"] for item in body["items"]}
    assert master_ids == {seeded["master_a1"], seeded["master_a2"]}
    assert body["total"] == 2
    # 别家师傅不出现
    assert seeded["master_b1"] not in master_ids


@pytest.mark.integration
async def test_master_list_carries_name_rating_and_status(
    api_client, seeded
) -> None:
    """师傅项带姓名 / 评分 / 状态（前端下拉框要显示）。"""
    response = await api_client.get(MASTERS_URL, headers=_admin_a_headers(seeded))
    assert response.status_code == 200
    items = {row["id"]: row for row in response.json()["items"]}

    first = items[seeded["master_a1"]]
    assert first["real_name"] == "师傅甲一"
    assert first["rating"] == "4.5"
    assert first["status"] == "ACTIVE"

    second = items[seeded["master_a2"]]
    assert second["real_name"] == "师傅甲二"
    # 没被评价过的师傅没有分数
    assert second["rating"] is None
    assert second["status"] == "PENDING"


@pytest.mark.integration
async def test_master_list_ignores_client_supplied_provider_id(
    api_client, seeded
) -> None:
    """请求里带 provider_id 不起作用（同订单列表）。"""
    headers = _admin_a_headers(seeded)
    without = await api_client.get(MASTERS_URL, headers=headers)
    with_param = await api_client.get(
        MASTERS_URL,
        params={"provider_id": seeded["provider_b"]},
        headers=headers,
    )
    assert with_param.status_code == 200
    assert with_param.json() == without.json()


# =====================================================================
# 鉴权
# =====================================================================


@pytest.mark.integration
async def test_provider_queries_require_authentication(api_client, seeded) -> None:
    """没有 token 一律 401。"""
    for url in (ORDERS_URL, MASTERS_URL):
        response = await api_client.get(url)
        assert response.status_code == 401, url
        assert response.json() == {"detail": "Unauthorized"}


@pytest.mark.integration
async def test_provider_queries_reject_non_provider_role(
    api_client, seeded
) -> None:
    """普通用户（没有服务商归属）-> 403。"""
    headers = _auth_header(seeded["plain_user"], UserRole.USER, None)
    for url in (ORDERS_URL, MASTERS_URL):
        response = await api_client.get(url, headers=headers)
        assert response.status_code == 403, url
        assert response.json() == {"detail": "Forbidden"}


@pytest.mark.integration
async def test_provider_role_without_provider_id_is_forbidden(
    api_client, seeded
) -> None:
    """角色是服务商侧、但没有归属 -> 同样 403。

    「角色不对」和「没有归属」不区分：区分开就等于泄露服务端状态。
    """
    headers = _auth_header(seeded["plain_user"], UserRole.PROVIDER_ADMIN, None)
    response = await api_client.get(ORDERS_URL, headers=headers)
    assert response.status_code == 403
    assert response.json() == {"detail": "Forbidden"}


@pytest.mark.integration
async def test_non_provider_role_with_provider_id_is_forbidden(
    api_client, seeded
) -> None:
    """角色不是服务商侧（哪怕 token 里带着 provider_id）-> 403。

    数据库的 CHECK 约束 ck_user_role_provider 不允许「普通用户 + 有归属」
    这种组合存在，但 token 是签出来的：鉴权不能只靠「数据上不可能」
    这一层假设。require_provider_scope 同时把住角色和归属两件事——
    只挡归属不挡角色，等于把作用域放宽了一半。
    """
    headers = _auth_header(seeded["plain_user"], UserRole.USER, seeded["provider_a"])
    for url in (ORDERS_URL, MASTERS_URL):
        response = await api_client.get(url, headers=headers)
        assert response.status_code == 403, url
        assert response.json() == {"detail": "Forbidden"}
