"""师傅端只读查询接口的测试（我的订单列表 / 订单详情 / 我的资料）。

必测点：

1. **只返回派给我的单**（R1/R5）：别家师傅的单既不在列表里，
   详情里也查不到；
2. **列表按状态过滤**：待接单 / 已接单 / 服务中三组各是各的，
   别的状态（比如待支付）传进来直接 422；
3. **归属不可伪造**：请求里带 master_id 不起作用（接口压根没这个入参，
   传了也被忽略，结果照样只有自己的单）；
4. **身份不可伪造**：角色不对 -> 403；账号没有师傅身份 -> 403；
   没 token -> 401；
5. **不暴露存在性**：别人的单与不存在的单是同一个 404、同一句话。

集成测试用的数据库是 TEST_DATABASE_URL 指向的独立测试库
（集成 fixture 每次 drop_all + create_all，绝不碰开发库）。
"""
from __future__ import annotations

import inspect
import os
from datetime import date, time, timedelta
from decimal import Decimal

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from tests.support import business_today
from app.api.v1 import master as master_router_module
from app.api.v1.errors import status_for
from app.core.auth import create_access_token
from app.core.database import get_session
from app.main import app
from app.models.address import Address
from app.models.base import Base
from app.models.catalog import ServiceCategory, ServiceItem
from app.models.enums import (
    MasterOrderStatus,
    MasterStatus,
    OrderStatus,
    PayStatus,
    UserRole,
)
from app.models.order import Order
from app.models.provider import Master, ServiceProvider
from app.models.schedule_slot import ScheduleSlot
from app.models.user import User
from app.schemas.master import MasterOrderDetail, MasterOrderItem, MasterProfile
from app.services.errors import MasterQueryForbiddenError

ORDERS_URL = "/api/v1/master/orders"
PROFILE_URL = "/api/v1/master/profile"

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

# ---------------------------------------------------------------------
# 种子数据里的 id
# ---------------------------------------------------------------------

MY_PROVIDER_ID = 1
OTHER_PROVIDER_ID = 7

MY_MASTER_ID = 1  # 我的师傅
OTHER_MASTER_ID = 2  # 别家师傅

CUSTOMER_USER_ID = 1
MY_MASTER_USER_ID = 2
OTHER_MASTER_USER_ID = 3
NO_MASTER_USER_ID = 4  # 角色是 MASTER，但 master 表里没有他的身份
PLAIN_USER_ID = 5

ITEM_ID = 2
SLOT_ID = 3
ADDRESS_ID = 4

# 订单
MY_PENDING_ORDER_ID = 1  # 派给我的，待接单
MY_PENDING_ORDER2_ID = 2  # 派给我的，待接单（第二笔）
OTHER_PENDING_ORDER_ID = 3  # 派给别家师傅，待接单
MY_ACCEPTED_ORDER_ID = 4  # 派给我的，已接单
MY_IN_SERVICE_ORDER_ID = 5  # 派给我的，服务中
NOT_DISPATCHED_ORDER_ID = 6  # 还没派单（谁都不属于）
MY_COMPLETED_ORDER_ID = 7  # 派给我的，已完成（详情查得到，列表里没有）

MY_PENDING_ORDER_NO = "OTO20260101000001"
MY_PENDING_ORDER2_NO = "OTO20260101000002"
OTHER_PENDING_ORDER_NO = "OTO20260101000003"
MY_ACCEPTED_ORDER_NO = "OTO20260101000004"
MY_IN_SERVICE_ORDER_NO = "OTO20260101000005"
NOT_DISPATCHED_ORDER_NO = "OTO20260101000006"
MY_COMPLETED_ORDER_NO = "OTO20260101000007"
MISSING_ORDER_NO = "OTO20260101009999"

BASE_PRICE = Decimal("100.00")


def _auth_header(user_id: int, role: UserRole, provider_id: int | None) -> dict[str, str]:
    token = create_access_token(user_id, role, provider_id)
    return {"Authorization": "Bearer {}".format(token)}


def _my_master_header() -> dict[str, str]:
    return _auth_header(MY_MASTER_USER_ID, UserRole.MASTER, None)


def _other_master_header() -> dict[str, str]:
    return _auth_header(OTHER_MASTER_USER_ID, UserRole.MASTER, None)


def _plain_user_header() -> dict[str, str]:
    return _auth_header(PLAIN_USER_ID, UserRole.USER, None)


def _no_master_identity_header() -> dict[str, str]:
    """角色是 MASTER，但 master 表里没有他的身份。"""
    return _auth_header(NO_MASTER_USER_ID, UserRole.MASTER, None)


# =====================================================================
# 单元测试：接口契约与字段集合（不碰数据库）
# =====================================================================


def test_router_endpoints_take_no_identity_parameters() -> None:
    """三个接口的签名里都没有 master_id / user_id / provider_id。

    师傅身份只能由服务端按 token 的 user_id 查 master 表得到，
    客户端自报一个就是自选身份（R1）。这是结构性保证：
    以后谁想加这个参数，测试先红。
    """
    for endpoint in (
        master_router_module.list_master_orders,
        master_router_module.get_master_order,
        master_router_module.get_master_profile,
    ):
        parameters = inspect.signature(endpoint).parameters
        assert "master_id" not in parameters
        assert "user_id" not in parameters
        assert "provider_id" not in parameters


def test_master_order_status_has_exactly_three_values() -> None:
    """师傅端的订单列表只认三种状态。

    这是业务规则（待接单 / 已接单待开工 / 服务中），不是「接口长什么样」，
    所以定义在 app.models.enums 里，接口层与 service 层按同一份判断。
    """
    assert {status.value for status in MasterOrderStatus} == {
        "PENDING_ACCEPT",
        "ACCEPTED",
        "IN_SERVICE",
    }


def test_response_field_sets() -> None:
    """响应字段集合固定。"""
    assert set(MasterOrderItem.model_fields) == {
        "order_no",
        "status",
        "amount",
        "item_id",
        "item_name",
        "slot_date",
        "slot_start_time",
        "slot_end_time",
        "created_at",
    }
    assert set(MasterOrderDetail.model_fields) == set(MasterOrderItem.model_fields) | {
        "id",
        "slot_id",
        "customer_contact",
        "customer_phone",
        "address_region",
        "address_detail",
    }
    assert set(MasterProfile.model_fields) == {
        "real_name",
        "rating",
        "status",
        "provider_name",
    }


def test_response_schemas_reject_extra_fields() -> None:
    """extra="forbid"：多带一个字段直接抛校验错误。"""
    with pytest.raises(Exception):
        MasterProfile(
            real_name="张师傅",
            rating=None,
            status=MasterStatus.ACTIVE,
            provider_name="甲服务商",
            master_id=9,
        )


def test_forbidden_error_maps_to_403() -> None:
    """「不是我的 / 没有师傅身份」-> 403。"""
    assert status_for(MasterQueryForbiddenError("当前账号没有师傅身份")) == 403


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
                    id=MY_PROVIDER_ID, name="甲服务商", contact_phone="13800000001"
                ),
                ServiceProvider(
                    id=OTHER_PROVIDER_ID, name="乙服务商", contact_phone="13800000002"
                ),
            ]
        )
        await session.flush()

        session.add_all(
            [
                User(id=CUSTOMER_USER_ID, phone="13900000001", role=UserRole.USER),
                # 师傅账号：师傅的归属权威来源是 master 表，
                # 所以 user.provider_id 必须为空（数据库 CHECK 约束强制）
                User(id=MY_MASTER_USER_ID, phone="13900000002", role=UserRole.MASTER),
                User(
                    id=OTHER_MASTER_USER_ID, phone="13900000003", role=UserRole.MASTER
                ),
                # 角色是师傅，但 master 表里没有他的身份
                User(id=NO_MASTER_USER_ID, phone="13900000004", role=UserRole.MASTER),
                User(id=PLAIN_USER_ID, phone="13900000005", role=UserRole.USER),
            ]
        )
        await session.flush()

        session.add(ServiceCategory(id=1, name="测试分类"))
        await session.flush()
        session.add(
            ServiceItem(
                id=ITEM_ID,
                category_id=1,
                name="日常保洁",
                base_price=BASE_PRICE,
                duration_min=60,
            )
        )
        await session.flush()
        session.add(
            Address(
                id=ADDRESS_ID,
                user_id=CUSTOMER_USER_ID,
                contact="张三",
                phone="13900000001",
                region="北京市朝阳区",
                detail="建国路 88 号 3 单元 501",
            )
        )
        await session.flush()
        session.add(
            ScheduleSlot(
                id=SLOT_ID,
                item_id=ITEM_ID,
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
                    rating=Decimal("4.8"),
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

        def _order(
            order_id: int,
            order_no: str,
            status: OrderStatus,
            master_id: int | None,
            provider_id: int | None = MY_PROVIDER_ID,
        ) -> Order:
            return Order(
                id=order_id,
                order_no=order_no,
                user_id=CUSTOMER_USER_ID,
                provider_id=provider_id,
                master_id=master_id,
                address_id=ADDRESS_ID,
                item_id=ITEM_ID,
                slot_id=SLOT_ID,
                amount=BASE_PRICE,
                status=status,
                pay_status=PayStatus.PAID,
            )

        session.add_all(
            [
                _order(
                    MY_PENDING_ORDER_ID,
                    MY_PENDING_ORDER_NO,
                    OrderStatus.PENDING_ACCEPT,
                    MY_MASTER_ID,
                ),
                _order(
                    MY_PENDING_ORDER2_ID,
                    MY_PENDING_ORDER2_NO,
                    OrderStatus.PENDING_ACCEPT,
                    MY_MASTER_ID,
                ),
                _order(
                    OTHER_PENDING_ORDER_ID,
                    OTHER_PENDING_ORDER_NO,
                    OrderStatus.PENDING_ACCEPT,
                    OTHER_MASTER_ID,
                    provider_id=OTHER_PROVIDER_ID,
                ),
                _order(
                    MY_ACCEPTED_ORDER_ID,
                    MY_ACCEPTED_ORDER_NO,
                    OrderStatus.ACCEPTED,
                    MY_MASTER_ID,
                ),
                _order(
                    MY_IN_SERVICE_ORDER_ID,
                    MY_IN_SERVICE_ORDER_NO,
                    OrderStatus.IN_SERVICE,
                    MY_MASTER_ID,
                ),
                _order(
                    NOT_DISPATCHED_ORDER_ID,
                    NOT_DISPATCHED_ORDER_NO,
                    OrderStatus.PENDING_DISPATCH,
                    None,
                ),
                _order(
                    MY_COMPLETED_ORDER_ID,
                    MY_COMPLETED_ORDER_NO,
                    OrderStatus.COMPLETED,
                    MY_MASTER_ID,
                ),
            ]
        )
        await session.flush()
        await session.commit()
    return db


@pytest.mark.integration
async def test_list_returns_only_my_orders(api_client, seeded) -> None:
    """待接单列表里只有派给我的两笔，别家师傅的那笔不出现。"""
    response = await api_client.get(
        f"{ORDERS_URL}?status=PENDING_ACCEPT",
        headers=_my_master_header(),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 2
    order_nos = {item["order_no"] for item in body["items"]}
    assert order_nos == {MY_PENDING_ORDER_NO, MY_PENDING_ORDER2_NO}
    # 别人的单、没派的单都不在列表里
    assert OTHER_PENDING_ORDER_NO not in order_nos
    assert NOT_DISPATCHED_ORDER_NO not in order_nos
    # 分页参数回显
    assert body["limit"] == 20
    assert body["offset"] == 0


@pytest.mark.integration
async def test_list_filters_by_status(api_client, seeded) -> None:
    """三组状态各是各的：已接单 / 服务中的单不会漏进待接单列表。"""
    accepted = await api_client.get(
        f"{ORDERS_URL}?status=ACCEPTED",
        headers=_my_master_header(),
    )
    in_service = await api_client.get(
        f"{ORDERS_URL}?status=IN_SERVICE",
        headers=_my_master_header(),
    )

    assert accepted.status_code == 200
    assert [item["order_no"] for item in accepted.json()["items"]] == [
        MY_ACCEPTED_ORDER_NO
    ]
    assert in_service.status_code == 200
    assert [item["order_no"] for item in in_service.json()["items"]] == [
        MY_IN_SERVICE_ORDER_NO
    ]


@pytest.mark.integration
async def test_list_rejects_status_outside_the_three(api_client, seeded) -> None:
    """只认三种状态：别的状态（比如待支付）直接 422。

    师傅端的工作队列只有三组，传别的状态没有意义——
    接口层用窄枚举挡住，service 那边也按同一份枚举再挡一次。
    """
    response = await api_client.get(
        f"{ORDERS_URL}?status=PENDING_PAY",
        headers=_my_master_header(),
    )

    assert response.status_code == 422


@pytest.mark.integration
async def test_client_supplied_master_id_is_ignored(api_client, seeded) -> None:
    """请求里带 master_id 不起作用：结果照样只有自己的单。

    接口压根没有 master_id 入参（FastAPI 会忽略多余的查询参数），
    师傅身份只由 token 决定——客户端自报身份等于自己挑单（R1）。
    """
    response = await api_client.get(
        f"{ORDERS_URL}?status=PENDING_ACCEPT&master_id={OTHER_MASTER_ID}",
        headers=_my_master_header(),
    )

    assert response.status_code == 200, response.text
    order_nos = {item["order_no"] for item in response.json()["items"]}
    assert order_nos == {MY_PENDING_ORDER_NO, MY_PENDING_ORDER2_NO}


@pytest.mark.integration
async def test_order_detail(api_client, seeded) -> None:
    """订单详情：自己的单查得到，带客户联系方式与上门地址。"""
    response = await api_client.get(
        "{}/{}".format(ORDERS_URL, MY_PENDING_ORDER_NO),
        headers=_my_master_header(),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["order_no"] == MY_PENDING_ORDER_NO
    assert body["status"] == "PENDING_ACCEPT"
    assert body["item_name"] == "日常保洁"
    assert body["customer_contact"] == "张三"
    assert body["customer_phone"] == "13900000001"
    assert body["address_region"] == "北京市朝阳区"
    assert body["address_detail"] == "建国路 88 号 3 单元 501"


@pytest.mark.integration
async def test_order_detail_of_other_master_is_404_same_shape(api_client, seeded) -> None:
    """别人的单与不存在的单：同一个 404、同一句话（不暴露存在性）。"""
    other = await api_client.get(
        "{}/{}".format(ORDERS_URL, OTHER_PENDING_ORDER_NO),
        headers=_my_master_header(),
    )
    missing = await api_client.get(
        "{}/{}".format(ORDERS_URL, MISSING_ORDER_NO),
        headers=_my_master_header(),
    )

    assert other.status_code == 404
    assert missing.status_code == 404
    # 两条文案只有「回显客户端自己给的订单号」这一处不同，
    # 其余完全一样：调用方区分不出「别人的单」与「不存在的单」。
    assert other.json()["detail"].replace(OTHER_PENDING_ORDER_NO, "{order_no}") == (
        missing.json()["detail"].replace(MISSING_ORDER_NO, "{order_no}")
    )
    # 文案里只有订单号，不含归属信息（承接师傅是谁、订单什么状态）
    assert other.json()["detail"] == "订单不存在：order_no={}".format(
        OTHER_PENDING_ORDER_NO
    )


@pytest.mark.integration
async def test_profile(api_client, seeded) -> None:
    """我的资料：姓名 / 评分 / 状态 / 所属服务商。"""
    response = await api_client.get(PROFILE_URL, headers=_my_master_header())

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["real_name"] == "张师傅"
    assert body["rating"] == "4.8"
    assert body["status"] == "ACTIVE"
    assert body["provider_name"] == "甲服务商"


@pytest.mark.integration
async def test_profile_of_master_without_rating(api_client, seeded) -> None:
    """还没被评价过的师傅：rating 是空，不是 0。"""
    response = await api_client.get(PROFILE_URL, headers=_other_master_header())

    assert response.status_code == 200, response.text
    assert response.json()["rating"] is None
    assert response.json()["provider_name"] == "乙服务商"


@pytest.mark.integration
async def test_non_master_role_is_403(api_client, seeded) -> None:
    """普通用户调师傅端接口 -> 403。"""
    response = await api_client.get(
        f"{ORDERS_URL}?status=PENDING_ACCEPT",
        headers=_plain_user_header(),
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Forbidden"


@pytest.mark.integration
async def test_account_without_master_identity_is_403(api_client, seeded) -> None:
    """角色是师傅、但 master 表里没有身份 -> 403（连订单都查不到）。"""
    response = await api_client.get(
        f"{ORDERS_URL}?status=PENDING_ACCEPT",
        headers=_no_master_identity_header(),
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "当前账号没有师傅身份"


@pytest.mark.integration
async def test_missing_token_is_401(api_client, seeded) -> None:
    """没 token -> 401。"""
    response = await api_client.get(f"{ORDERS_URL}?status=PENDING_ACCEPT")

    assert response.status_code == 401
