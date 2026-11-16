"""用户侧只读查询接口的测试（品类 / 服务项 / 时段余量 / 我的订单）。

四个必测点（每条都有测试盯着）：

1. **用户 A 查订单列表看不到用户 B 的**（R5）；
2. **订单详情查别人的 -> 404 同构**（与「根本不存在」响应完全一样）；
3. **时段余量 = capacity - used，已约满的时段不返回**；
4. **分页**：25 笔订单，limit=20 -> 第一页 20 条、第二页 5 条。

另外补了目录侧的行为（品类树、品类下的服务项、过去日期的时段、
分页上限收敛、未鉴权 401）。

集成测试用的数据库是 TEST_DATABASE_URL 指向的独立测试库
（集成 fixture 每次 drop_all + create_all，绝不碰开发库）。
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
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
from app.models.enums import CatalogStatus, OrderStatus, PayStatus, UserRole
from app.models.order import Order
from app.models.schedule_slot import ScheduleSlot
from app.models.user import User
from tests.support import business_today

CATALOG_URL = "/api/v1/catalog"
ORDERS_URL = "/api/v1/orders"

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

# 造 25 笔订单用来验分页
ORDER_COUNT = 25


def _auth_header(user_id: int, **kwargs) -> dict[str, str]:
    """生成带合法 token 的请求头（默认普通 C 端用户身份）。"""
    kwargs.setdefault("role", UserRole.USER)
    kwargs.setdefault("provider_id", None)
    token = create_access_token(user_id, **kwargs)
    return {"Authorization": "Bearer {}".format(token)}


# =====================================================================
# fixture
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


@dataclass
class Seed:
    user_a_id: int
    user_b_id: int
    root_category_id: int
    sub_category_id: int
    inactive_category_id: int
    item_id: int
    sub_item_id: int
    inactive_item_id: int
    address_a_id: int
    address_b_id: int
    slot_ids: dict[str, int]
    order_a_nos: list[str]
    order_b_no: str
    newest_order_no: str


@pytest.fixture
async def seeded(db) -> Seed:
    """铺好查询要用的数据。

    - 用户 A（1）、用户 B（2）
    - 品类 1「家庭保洁」（一级、启用）、品类 2「深度保洁」（子品类、启用）、
      品类 3「已下架品类」（一级、停用）
    - 服务项 10（品类 1，启用）、11（品类 2，启用）、12（品类 1，停用）
    - 时段：20（明天，剩 2）、21（明天，已满）、22（明天，剩 4）、
      23（今天，剩 5）、24（昨天）
    - 订单：A 25 笔、B 1 笔
    """
    maker = async_sessionmaker(db, class_=AsyncSession, expire_on_commit=False)
    today = business_today()
    tomorrow = today + timedelta(days=1)
    yesterday = today - timedelta(days=1)

    async with maker() as session:
        # 模型层没有 relationship，flush 顺序按 mapper 类名字母序（不是外键依赖序），
        # 所以按依赖顺序逐个 flush，避免外键违例
        session.add(User(id=1, phone="13800000001"))
        session.add(User(id=2, phone="13800000002"))
        await session.flush()

        session.add(
            ServiceCategory(id=1, name="家庭保洁", parent_id=None, sort_order=1)
        )
        session.add(
            ServiceCategory(id=2, name="深度保洁", parent_id=1, sort_order=1)
        )
        session.add(
            ServiceCategory(
                id=3,
                name="已下架品类",
                parent_id=None,
                sort_order=2,
                status=CatalogStatus.INACTIVE,
            )
        )
        await session.flush()

        session.add(
            ServiceItem(
                id=10,
                category_id=1,
                name="日常保洁",
                base_price=Decimal("100.00"),
                duration_min=60,
                status=CatalogStatus.ACTIVE,
            )
        )
        session.add(
            ServiceItem(
                id=11,
                category_id=2,
                name="油烟机清洗",
                base_price=Decimal("200.00"),
                duration_min=90,
                status=CatalogStatus.ACTIVE,
            )
        )
        session.add(
            ServiceItem(
                id=12,
                category_id=1,
                name="已下架服务项",
                base_price=Decimal("150.00"),
                duration_min=60,
                status=CatalogStatus.INACTIVE,
            )
        )
        await session.flush()

        session.add(
            Address(
                id=30,
                user_id=1,
                contact="张三",
                phone="13800000001",
                region="北京",
                detail="某街道 1 号",
            )
        )
        session.add(
            Address(
                id=31,
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
                id=20,
                item_id=10,
                date=tomorrow,
                start_time=time(9, 0),
                end_time=time(12, 0),
                capacity=3,
                used=1,
            )
        )
        session.add(
            ScheduleSlot(
                id=21,
                item_id=10,
                date=tomorrow,
                start_time=time(13, 0),
                end_time=time(15, 0),
                capacity=2,
                used=2,
            )
        )
        session.add(
            ScheduleSlot(
                id=22,
                item_id=10,
                date=tomorrow,
                start_time=time(15, 0),
                end_time=time(17, 0),
                capacity=4,
                used=0,
            )
        )
        session.add(
            ScheduleSlot(
                id=23,
                item_id=10,
                date=today,
                start_time=time(9, 0),
                end_time=time(12, 0),
                capacity=5,
                used=0,
            )
        )
        session.add(
            ScheduleSlot(
                id=24,
                item_id=10,
                date=yesterday,
                start_time=time(9, 0),
                end_time=time(12, 0),
                capacity=5,
                used=0,
            )
        )
        await session.flush()

        # A 的 25 笔订单：created_at 递增（最早的在前）
        base = datetime.now(timezone.utc) - timedelta(days=1)
        order_a_nos = []
        for index in range(ORDER_COUNT):
            order_no = "OTO2026010100{:04d}".format(index)
            order_a_nos.append(order_no)
            session.add(
                Order(
                    order_no=order_no,
                    user_id=1,
                    provider_id=None,
                    master_id=None,
                    address_id=30,
                    item_id=10,
                    slot_id=20,
                    amount=Decimal("100.00"),
                    status=OrderStatus.PENDING_PAY,
                    pay_status=PayStatus.UNPAID,
                    created_at=base + timedelta(seconds=index),
                )
            )
        # B 的 1 笔订单：created_at 最新（A 列表排序时要被排除掉）
        session.add(
            Order(
                order_no="OTO20260101009999",
                user_id=2,
                provider_id=None,
                master_id=None,
                address_id=31,
                item_id=10,
                slot_id=20,
                amount=Decimal("100.00"),
                status=OrderStatus.PENDING_PAY,
                pay_status=PayStatus.UNPAID,
                created_at=base + timedelta(days=1),
            )
        )
        await session.commit()

    return Seed(
        user_a_id=1,
        user_b_id=2,
        root_category_id=1,
        sub_category_id=2,
        inactive_category_id=3,
        item_id=10,
        sub_item_id=11,
        inactive_item_id=12,
        address_a_id=30,
        address_b_id=31,
        slot_ids={"剩2": 20, "已满": 21, "剩4": 22, "今天": 23, "昨天": 24},
        order_a_nos=order_a_nos,
        order_b_no="OTO20260101009999",
        newest_order_no=order_a_nos[-1],
    )


async def _add_orders(
    db,
    *,
    user_id: int,
    count: int,
    start_index: int,
    address_id: int = 30,
    item_id: int = 10,
    slot_id: int = 20,
) -> None:
    """再给某个用户造 count 笔订单。

    用来把订单数推过 100：只有订单数超过上限，
    「上限生效」和「上限没生效」才能被区分开（订单少的时候两者看起来一样）。
    """
    maker = async_sessionmaker(db, class_=AsyncSession, expire_on_commit=False)
    base = datetime.now(timezone.utc) - timedelta(days=2)
    async with maker() as session:
        for index in range(count):
            session.add(
                Order(
                    order_no="OTO2026020200{:04d}".format(start_index + index),
                    user_id=user_id,
                    provider_id=None,
                    master_id=None,
                    address_id=address_id,
                    item_id=item_id,
                    slot_id=slot_id,
                    amount=Decimal("100.00"),
                    status=OrderStatus.PENDING_PAY,
                    pay_status=PayStatus.UNPAID,
                    created_at=base + timedelta(seconds=index),
                )
            )
        await session.commit()


# =====================================================================
# 必测 1：用户 A 查订单列表看不到用户 B 的（R5）
# =====================================================================


@pytest.mark.integration
async def test_order_list_never_returns_other_users_orders(
    api_client, seeded
) -> None:
    """A 的列表里没有 B 的订单，且 B 的订单数不进 A 的 total。"""
    response = await api_client.get(
        ORDERS_URL,
        params={"limit": 100},
        headers=_auth_header(seeded.user_a_id),
    )
    assert response.status_code == 200
    body = response.json()

    order_nos = [item["order_no"] for item in body["items"]]
    assert seeded.order_b_no not in order_nos
    assert set(order_nos) == set(seeded.order_a_nos)
    # total 是「这个用户的订单总数」，也不该把别人的算进来
    assert body["total"] == ORDER_COUNT


@pytest.mark.integration
async def test_order_list_of_b_only_returns_b_orders(api_client, seeded) -> None:
    """反过来看：B 的列表里只有 B 那一笔。"""
    response = await api_client.get(
        ORDERS_URL,
        headers=_auth_header(seeded.user_b_id),
    )
    assert response.status_code == 200
    body = response.json()
    assert [item["order_no"] for item in body["items"]] == [seeded.order_b_no]
    assert body["total"] == 1


# =====================================================================
# 必测 2：订单详情查别人的 -> 404 同构
# =====================================================================


@pytest.mark.integration
async def test_order_detail_of_other_users_order_returns_404(
    api_client, seeded
) -> None:
    """A 查 B 的订单 -> 404。"""
    response = await api_client.get(
        "{}/{}".format(ORDERS_URL, seeded.order_b_no),
        headers=_auth_header(seeded.user_a_id),
    )
    assert response.status_code == 404


@pytest.mark.integration
async def test_order_detail_not_found_and_not_mine_are_isomorphic(
    api_client, seeded
) -> None:
    """「不是我的」与「根本不存在」返回**完全一样**的 404。

    文案模板一致（把数字换成占位符后逐字相同）= 调用方没法靠错误差异
    探测某个订单号存不存在、归谁。
    """
    not_mine = await api_client.get(
        "{}/{}".format(ORDERS_URL, seeded.order_b_no),
        headers=_auth_header(seeded.user_a_id),
    )
    missing = await api_client.get(
        "{}/{}".format(ORDERS_URL, "OTO20260101008888"),
        headers=_auth_header(seeded.user_a_id),
    )
    assert not_mine.status_code == 404
    assert missing.status_code == 404

    template = re.compile(r"\d+")
    assert template.sub("#", not_mine.json()["detail"]) == template.sub(
        "#", missing.json()["detail"]
    )
    # 文案里不得出现归属信息（否则等于承认订单存在）
    for detail in (not_mine.json()["detail"], missing.json()["detail"]):
        assert "user" not in detail.lower()
        assert "用户" not in detail


@pytest.mark.integration
async def test_order_detail_of_my_own_order_returns_it(api_client, seeded) -> None:
    """自己的订单能查到详情。"""
    response = await api_client.get(
        "{}/{}".format(ORDERS_URL, seeded.newest_order_no),
        headers=_auth_header(seeded.user_a_id),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["order_no"] == seeded.newest_order_no
    assert body["item_name"] == "日常保洁"
    assert body["amount"] == "100.00"
    assert body["address_id"] == seeded.address_a_id
    # 内部派单信息不外发
    assert "provider_id" not in body
    assert "master_id" not in body


# =====================================================================
# 必测 3：时段余量 = capacity - used，已满的时段不返回
# =====================================================================


@pytest.mark.integration
async def test_slots_available_is_capacity_minus_used(api_client, seeded) -> None:
    """available = capacity - used，且已约满的时段不出现在列表里。"""
    tomorrow = (business_today() + timedelta(days=1)).isoformat()
    response = await api_client.get(
        "/api/v1/items/{}/slots".format(seeded.item_id),
        params={"date": tomorrow},
        headers=_auth_header(seeded.user_a_id),
    )
    assert response.status_code == 200
    slots = response.json()

    by_id = {slot["id"]: slot for slot in slots}
    # 已满的时段（capacity=2, used=2）不返回
    assert seeded.slot_ids["已满"] not in by_id
    # 余量对得上
    assert by_id[seeded.slot_ids["剩2"]]["capacity"] == 3
    assert by_id[seeded.slot_ids["剩2"]]["used"] == 1
    assert by_id[seeded.slot_ids["剩2"]]["available"] == 2
    assert by_id[seeded.slot_ids["剩4"]]["capacity"] == 4
    assert by_id[seeded.slot_ids["剩4"]]["used"] == 0
    assert by_id[seeded.slot_ids["剩4"]]["available"] == 4
    # 每一条都自洽：available 就是 capacity - used
    for slot in slots:
        assert slot["available"] == slot["capacity"] - slot["used"]
        assert slot["available"] > 0


@pytest.mark.integration
async def test_slots_of_past_date_returns_empty(api_client, seeded) -> None:
    """过去的日期没有可约时段（返回空列表，不是错误）。"""
    yesterday = (business_today() - timedelta(days=1)).isoformat()
    response = await api_client.get(
        "/api/v1/items/{}/slots".format(seeded.item_id),
        params={"date": yesterday},
        headers=_auth_header(seeded.user_a_id),
    )
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.integration
async def test_slots_of_today_are_returned(api_client, seeded) -> None:
    """当天的时段要出现（规则是 date >= today，不是 > today）。"""
    today = business_today().isoformat()
    response = await api_client.get(
        "/api/v1/items/{}/slots".format(seeded.item_id),
        params={"date": today},
        headers=_auth_header(seeded.user_a_id),
    )
    assert response.status_code == 200
    slot_ids = [slot["id"] for slot in response.json()]
    assert slot_ids == [seeded.slot_ids["今天"]]


@pytest.mark.integration
async def test_slots_of_unknown_item_returns_404(api_client, seeded) -> None:
    """服务项不存在 -> 404。"""
    tomorrow = (business_today() + timedelta(days=1)).isoformat()
    response = await api_client.get(
        "/api/v1/items/999999/slots",
        params={"date": tomorrow},
        headers=_auth_header(seeded.user_a_id),
    )
    assert response.status_code == 404


# =====================================================================
# 必测 4：分页（25 笔订单，limit=20 -> 20 + 5）
# =====================================================================


@pytest.mark.integration
async def test_order_list_pagination_splits_25_orders_into_20_and_5(
    api_client, seeded
) -> None:
    """第一页 20 条，第二页 5 条，两页不重叠、并集是全部订单。"""
    headers = _auth_header(seeded.user_a_id)

    first = await api_client.get(
        ORDERS_URL, params={"limit": 20, "offset": 0}, headers=headers
    )
    second = await api_client.get(
        ORDERS_URL, params={"limit": 20, "offset": 20}, headers=headers
    )
    assert first.status_code == 200
    assert second.status_code == 200

    first_body = first.json()
    second_body = second.json()
    assert len(first_body["items"]) == 20
    assert len(second_body["items"]) == 5
    assert first_body["total"] == ORDER_COUNT
    assert second_body["total"] == ORDER_COUNT

    first_nos = [item["order_no"] for item in first_body["items"]]
    second_nos = [item["order_no"] for item in second_body["items"]]
    # 两页不重叠
    assert set(first_nos) & set(second_nos) == set()
    # 并集正好是全部 25 笔
    assert set(first_nos) | set(second_nos) == set(seeded.order_a_nos)
    # 按创建时间倒序：第一页第一条是最新的一笔
    assert first_nos[0] == seeded.newest_order_no


@pytest.mark.integration
async def test_order_list_default_limit_is_20(api_client, seeded) -> None:
    """不传 limit 时默认每页 20 条。"""
    response = await api_client.get(ORDERS_URL, headers=_auth_header(seeded.user_a_id))
    assert response.status_code == 200
    body = response.json()
    assert body["limit"] == 20
    assert len(body["items"]) == 20


@pytest.mark.integration
async def test_order_list_limit_above_max_is_capped(api_client, seeded, db) -> None:
    """limit 超过上限时按 100 算（不报错）。

    订单数必须**超过** 100 才有意义：只有 25 笔时，「返回 25 条」和
    「返回 100 条上限内的全部」看起来一模一样，测试会假绿。
    """
    await _add_orders(db, user_id=seeded.user_a_id, count=100, start_index=1000)

    response = await api_client.get(
        ORDERS_URL,
        params={"limit": 500},
        headers=_auth_header(seeded.user_a_id),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["limit"] == 100
    assert len(body["items"]) == 100
    assert body["total"] == ORDER_COUNT + 100


# =====================================================================
# 目录侧行为
# =====================================================================


@pytest.mark.integration
async def test_catalog_returns_tree_with_children_and_skips_inactive(
    api_client, seeded
) -> None:
    """品类树：一级品类带子品类；停用的品类不出现。"""
    response = await api_client.get(
        CATALOG_URL, headers=_auth_header(seeded.user_a_id)
    )
    assert response.status_code == 200
    categories = response.json()

    ids = [category["id"] for category in categories]
    assert seeded.root_category_id in ids
    assert seeded.inactive_category_id not in ids

    root = next(c for c in categories if c["id"] == seeded.root_category_id)
    child_ids = [child["id"] for child in root["children"]]
    assert child_ids == [seeded.sub_category_id]


@pytest.mark.integration
async def test_category_items_lists_only_active_items(api_client, seeded) -> None:
    """品类下的服务项只含启用的。"""
    response = await api_client.get(
        "{}/{}/items".format(CATALOG_URL, seeded.root_category_id),
        headers=_auth_header(seeded.user_a_id),
    )
    assert response.status_code == 200
    items = response.json()
    assert [item["id"] for item in items] == [seeded.item_id]
    assert Decimal(str(items[0]["base_price"])) == Decimal("100.00")

    # 子品类的服务项在子品类下，不混进父品类
    sub = await api_client.get(
        "{}/{}/items".format(CATALOG_URL, seeded.sub_category_id),
        headers=_auth_header(seeded.user_a_id),
    )
    assert sub.status_code == 200
    assert [item["id"] for item in sub.json()] == [seeded.sub_item_id]


@pytest.mark.integration
async def test_category_items_unknown_and_inactive_are_both_404(
    api_client, seeded
) -> None:
    """品类不存在与品类已停用 -> 404，且文案一致。"""
    missing = await api_client.get(
        "{}/999999/items".format(CATALOG_URL),
        headers=_auth_header(seeded.user_a_id),
    )
    inactive = await api_client.get(
        "{}/{}/items".format(CATALOG_URL, seeded.inactive_category_id),
        headers=_auth_header(seeded.user_a_id),
    )
    assert missing.status_code == 404
    assert inactive.status_code == 404
    template = re.compile(r"\d+")
    assert template.sub("#", missing.json()["detail"]) == template.sub(
        "#", inactive.json()["detail"]
    )


# =====================================================================
# 鉴权
# =====================================================================


@pytest.mark.integration
async def test_queries_require_authentication(api_client, seeded) -> None:
    """没有 token 的查询一律 401。"""
    tomorrow = (business_today() + timedelta(days=1)).isoformat()
    cases = [
        ("GET", CATALOG_URL, None),
        ("GET", "{}/{}/items".format(CATALOG_URL, seeded.root_category_id), None),
        (
            "GET",
            "/api/v1/items/{}/slots".format(seeded.item_id),
            {"date": tomorrow},
        ),
        ("GET", ORDERS_URL, None),
        ("GET", "{}/{}".format(ORDERS_URL, seeded.order_a_nos[0]), None),
    ]
    for method, url, params in cases:
        response = await api_client.request(method, url, params=params)
        assert response.status_code == 401, url
        assert response.json() == {"detail": "Unauthorized"}
