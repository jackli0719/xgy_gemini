"""API 层四端闭环端到端测试（E2E-01）。

一条 happy path 走完**四个角色**：

    客户下单 -> 支付 -> 服务商派单 -> 师傅接单 -> 师傅开工 -> 师傅完工 -> 客户确认完成

与其它测试的区别：

- **直打 app，不起真实 HTTP 服务**：用 ``httpx.ASGITransport`` 把请求
  直接送进 FastAPI 应用。走的是完整的「路由 -> service -> 数据库」链路，
  没有任何 mock，但省掉了端口与进程管理。
- **全程真实 API**：不 mock service、不打桩数据库，所有判断都来自
  真实实现（状态机、状态流转留痕、租户隔离都真的在跑）。
- **一个 order_no 贯穿全程**：十步用的是同一笔订单，每一步都断言
  状态码 + 响应里的状态字段，最后再回头查库核对状态与留痕。

跑法（只跑这一个文件）::

    make test-file FILE=tests/e2e/test_happy_path.py

集成测试用的数据库是 TEST_DATABASE_URL 指向的独立测试库
（fixture 每次 drop_all + create_all，绝不碰开发库）。
"""
from __future__ import annotations

import os
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from tests.support import business_today
from app.core.config import settings
from app.core.database import get_session
from app.main import app
from app.models.base import Base
from app.models.catalog import ServiceCategory, ServiceItem
from app.models.enums import (
    MasterStatus,
    OperatorType,
    OrderStatus,
    PayStatus,
    ProviderStatus,
    UserRole,
)
from app.models.order import Order, OrderStatusLog
from app.models.provider import Master, ServiceProvider
from app.models.schedule_slot import ScheduleSlot
from app.models.user import User

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

# ---------------------------------------------------------------------
# 三个角色的手机号
# ---------------------------------------------------------------------

CUSTOMER_PHONE = "13800000001"  # 客户（普通用户）
PROVIDER_ADMIN_PHONE = "13800000002"  # 服务商管理员
MASTER_PHONE = "13800000003"  # 师傅

# 验证码是 MVP 占位（settings.login_sms_code，dev 下默认 123456）。
# 这里取配置值而不是写死：环境里换过码时测试照样跑得通。
LOGIN_CODE = settings.login_sms_code

# 目录数据
CATEGORY_NAME = "家政保洁"
ITEM_NAME = "日常保洁"
MASTER_NAME = "张师傅"
PROVIDER_NAME = "E2E 服务商"
BASE_PRICE = Decimal("100.00")


def _report(step: int, title: str, detail: str) -> None:
    """打印一步的结果（-s 时可见）。"""
    print("[E2E-01] 步骤 {} {} -> {}".format(step, title, detail))


# =====================================================================
# fixture
# =====================================================================


@pytest.fixture
async def db():
    """每个集成测试一块干净的库。

    跑前：drop_all + create_all，业务表清空；
    跑后：TRUNCATE 业务表，留下一个干净的库给下一个测试。
    """
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
        await _truncate_business_tables(engine)
        await engine.dispose()


async def _truncate_business_tables(engine) -> None:
    """跑完把业务表清空（顺序无所谓，用 CASCADE 一次清掉）。"""
    table_names = ", ".join(
        '"{}"'.format(table.name) for table in reversed(Base.metadata.sorted_tables)
    )
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "TRUNCATE TABLE {} RESTART IDENTITY CASCADE".format(table_names)
            )
        )


@pytest.fixture
async def seeded(db) -> dict[str, int]:
    """种一个服务商 + 服务商管理员 + 师傅账号 + 师傅 + 品类 + 服务项 + 时段。

    **不显式指定 id**：让数据库序列自己分配。显式写 id 会让序列停在 1，
    客户登录自动建号拿到的 id 就会撞上已有的行。

    **不种客户账号**：C 端「登录即注册」，客户第一次登录时自动建号
    （app/services/login.py），这正是要验的那条路径。
    """
    maker = async_sessionmaker(db, class_=AsyncSession, expire_on_commit=False)
    tomorrow = business_today() + timedelta(days=1)
    async with maker() as session:
        provider = ServiceProvider(
            name=PROVIDER_NAME,
            contact_phone="13900000000",
            status=ProviderStatus.ACTIVE,
        )
        session.add(provider)
        await session.flush()

        provider_admin = User(
            phone=PROVIDER_ADMIN_PHONE,
            nickname="E2E 管理员",
            role=UserRole.PROVIDER_ADMIN,
            provider_id=provider.id,
        )
        # 师傅账号的归属权威来源是 master 表，
        # 所以 user.provider_id 必须为空（数据库 CHECK 约束强制）
        master_user = User(
            phone=MASTER_PHONE,
            nickname="E2E 师傅",
            role=UserRole.MASTER,
            provider_id=None,
        )
        session.add_all([provider_admin, master_user])
        await session.flush()

        master = Master(
            provider_id=provider.id,
            user_id=master_user.id,
            real_name=MASTER_NAME,
            status=MasterStatus.ACTIVE,
            rating=Decimal("4.8"),
        )
        session.add(master)
        await session.flush()

        category = ServiceCategory(name=CATEGORY_NAME)
        session.add(category)
        await session.flush()

        item = ServiceItem(
            category_id=category.id,
            name=ITEM_NAME,
            base_price=BASE_PRICE,
            duration_min=60,
        )
        session.add(item)
        await session.flush()

        slot = ScheduleSlot(
            item_id=item.id,
            date=tomorrow,
            start_time=time(9, 0),
            end_time=time(12, 0),
            capacity=5,
            used=0,
        )
        session.add(slot)
        await session.flush()
        await session.commit()

        return {
            "provider_id": provider.id,
            "provider_admin_id": provider_admin.id,
            "master_user_id": master_user.id,
            "master_id": master.id,
            "category_id": category.id,
            "item_id": item.id,
            "slot_id": slot.id,
        }


@pytest.fixture
async def api_client(db, monkeypatch):
    """接测试库的 HTTP 客户端（集成测试用）。

    mock 支付回调只在 dev 环境开放（app/api/v1/pay.py）。
    容器里 APP_ENV=dev；这里再显式切一次，免得换个环境跑就挂在 403 上。
    """
    monkeypatch.setattr(settings, "app_env", "dev")
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


# =====================================================================
# 辅助
# =====================================================================


async def _login(client: httpx.AsyncClient, phone: str) -> dict:
    """登录并返回响应体（断言 200 与 token 字段）。"""
    response = await client.post(
        "/api/v1/auth/login", json={"phone": phone, "code": LOGIN_CODE}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    return body


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": "Bearer {}".format(token)}


def _find_category(nodes: list[dict], name: str) -> dict:
    """在品类树里按名字找品类（含子品类）。"""
    for node in nodes:
        if node["name"] == name:
            return node
        found = _find_category(node.get("children") or [], name)
        if found is not None:
            return found
    return None


# =====================================================================
# 一条 happy path：十个步骤
# =====================================================================


@pytest.mark.integration
async def test_four_role_happy_path(api_client, seeded, db) -> None:
    """四端闭环：客户下单 -> 支付 -> 派单 -> 接单 -> 开工 -> 完工 -> 确认完成。"""
    tomorrow = business_today() + timedelta(days=1)

    # ---------------------------------------------------------------
    # 步骤 1：客户登录
    # ---------------------------------------------------------------
    customer_login = await _login(api_client, CUSTOMER_PHONE)
    customer_token = customer_login["access_token"]
    assert customer_login["user"]["role"] == UserRole.USER.value
    assert customer_login["user"]["provider_id"] is None
    _report(
        1,
        "客户登录",
        "200 user_id={} role=USER".format(customer_login["user"]["id"]),
    )

    # ---------------------------------------------------------------
    # 步骤 2：查目录（品类 -> 服务项 -> 时段）
    # ---------------------------------------------------------------
    catalog = await api_client.get("/api/v1/catalog", headers=_auth(customer_token))
    assert catalog.status_code == 200, catalog.text
    category = _find_category(catalog.json(), CATEGORY_NAME)
    assert category is not None, "目录里找不到品类 {}".format(CATEGORY_NAME)

    items = await api_client.get(
        "/api/v1/catalog/{}/items".format(category["id"]),
        headers=_auth(customer_token),
    )
    assert items.status_code == 200, items.text
    item_ids = [row["id"] for row in items.json() if row["name"] == ITEM_NAME]
    assert item_ids, "品类下找不到服务项 {}".format(ITEM_NAME)
    item_id = item_ids[0]

    slots = await api_client.get(
        "/api/v1/items/{}/slots".format(item_id),
        params={"date": tomorrow.isoformat()},
        headers=_auth(customer_token),
    )
    assert slots.status_code == 200, slots.text
    slot_ids = [row["id"] for row in slots.json()]
    assert slot_ids, "{} 在 {} 没有可预约时段".format(ITEM_NAME, tomorrow)
    slot_id = slot_ids[0]
    _report(
        2,
        "查目录",
        "200 category_id={} item_id={} slot_id={}".format(
            category["id"], item_id, slot_id
        ),
    )

    # ---------------------------------------------------------------
    # 步骤 3：新建收货地址
    # ---------------------------------------------------------------
    address = await api_client.post(
        "/api/v1/addresses",
        json={
            "contact": "张三",
            "phone": "13900000001",
            "region": "北京市朝阳区",
            "detail": "某街道 1 号",
        },
        headers=_auth(customer_token),
    )
    assert address.status_code == 201, address.text
    address_body = address.json()
    assert address_body["contact"] == "张三"
    address_id = address_body["id"]
    _report(3, "新建地址", "201 address_id={}".format(address_id))

    # ---------------------------------------------------------------
    # 步骤 4：下单 -> 待支付
    # ---------------------------------------------------------------
    order = await api_client.post(
        "/api/v1/orders",
        json={"item_id": item_id, "slot_id": slot_id, "address_id": address_id},
        headers=_auth(customer_token),
    )
    assert order.status_code == 201, order.text
    order_body = order.json()
    assert order_body["status"] == OrderStatus.PENDING_PAY.value
    # 金额是 Decimal，序列化成 JSON 时是字符串（"100.00"）
    assert Decimal(order_body["amount"]) == BASE_PRICE
    order_no = order_body["order_no"]
    order_id = order_body["id"]
    assert order_no.startswith("OTO")
    _report(
        4,
        "下单",
        "201 status=PENDING_PAY order_no={}".format(order_no),
    )

    # ---------------------------------------------------------------
    # 步骤 5：mock 支付回调 -> 待派单
    # ---------------------------------------------------------------
    pay = await api_client.post(
        "/api/v1/pay/mock-notify", json={"order_no": order_no}
    )
    assert pay.status_code == 200, pay.text
    pay_body = pay.json()
    assert pay_body["status"] == OrderStatus.PENDING_DISPATCH.value
    assert pay_body["pay_status"] == PayStatus.PAID.value
    _report(
        5,
        "支付",
        "200 status=PENDING_DISPATCH pay_status=PAID",
    )

    # ---------------------------------------------------------------
    # 步骤 6：服务商派单 -> 待接单
    # ---------------------------------------------------------------
    provider_login = await _login(api_client, PROVIDER_ADMIN_PHONE)
    provider_token = provider_login["access_token"]
    assert provider_login["user"]["role"] == UserRole.PROVIDER_ADMIN.value
    assert provider_login["user"]["provider_id"] == seeded["provider_id"]

    masters = await api_client.get(
        "/api/v1/provider/masters", headers=_auth(provider_token)
    )
    assert masters.status_code == 200, masters.text
    master_ids = [
        row["id"] for row in masters.json()["items"] if row["real_name"] == MASTER_NAME
    ]
    assert master_ids, "本商师傅列表里找不到 {}".format(MASTER_NAME)
    master_id = master_ids[0]

    # 待派单列表里能看到这笔单（公共待派单池）
    pending = await api_client.get(
        "/api/v1/provider/orders",
        params={"status": OrderStatus.PENDING_DISPATCH.value},
        headers=_auth(provider_token),
    )
    assert pending.status_code == 200, pending.text
    pending_nos = [row["order_no"] for row in pending.json()["items"]]
    assert order_no in pending_nos, "待派单列表里看不到 {}".format(order_no)

    dispatch = await api_client.post(
        "/api/v1/orders/{}/dispatch".format(order_id),
        json={"master_id": master_id},
        headers=_auth(provider_token),
    )
    assert dispatch.status_code == 200, dispatch.text
    dispatch_body = dispatch.json()
    assert dispatch_body["status"] == OrderStatus.PENDING_ACCEPT.value
    assert dispatch_body["master_id"] == master_id
    _report(
        6,
        "服务商派单",
        "200 status=PENDING_ACCEPT master_id={}".format(master_id),
    )

    # ---------------------------------------------------------------
    # 步骤 7：师傅接单 -> 已接单
    # ---------------------------------------------------------------
    master_login = await _login(api_client, MASTER_PHONE)
    master_token = master_login["access_token"]
    assert master_login["user"]["role"] == UserRole.MASTER.value

    accept = await api_client.post(
        "/api/v1/orders/{}/accept".format(order_no),
        headers=_auth(master_token),
    )
    assert accept.status_code == 200, accept.text
    accept_body = accept.json()
    assert accept_body["status"] == OrderStatus.ACCEPTED.value
    assert accept_body["master_id"] == master_id
    _report(7, "师傅接单", "200 status=ACCEPTED")

    # ---------------------------------------------------------------
    # 步骤 8：师傅开工 -> 服务中
    # ---------------------------------------------------------------
    start = await api_client.post(
        "/api/v1/orders/{}/start".format(order_no),
        headers=_auth(master_token),
    )
    assert start.status_code == 200, start.text
    start_body = start.json()
    assert start_body["status"] == OrderStatus.IN_SERVICE.value
    assert start_body["completed_at"] is None
    _report(8, "师傅开工", "200 status=IN_SERVICE")

    # ---------------------------------------------------------------
    # 步骤 9：师傅完工 -> 待确认
    # ---------------------------------------------------------------
    finish = await api_client.post(
        "/api/v1/orders/{}/finish".format(order_no),
        headers=_auth(master_token),
    )
    assert finish.status_code == 200, finish.text
    finish_body = finish.json()
    assert finish_body["status"] == OrderStatus.PENDING_CONFIRM.value
    assert finish_body["completed_at"] is None
    _report(9, "师傅完工", "200 status=PENDING_CONFIRM")

    # ---------------------------------------------------------------
    # 步骤 10：客户确认完成 -> 已完成
    # ---------------------------------------------------------------
    confirm = await api_client.post(
        "/api/v1/orders/{}/confirm".format(order_no),
        headers=_auth(customer_token),
    )
    assert confirm.status_code == 200, confirm.text
    confirm_body = confirm.json()
    assert confirm_body["status"] == OrderStatus.COMPLETED.value
    assert confirm_body["completed_at"] is not None
    _report(10, "客户确认完成", "200 status=COMPLETED")

    # ---------------------------------------------------------------
    # 收尾核对：三个 token 相互独立，库里状态与留痕都对得上
    # ---------------------------------------------------------------
    assert len({customer_token, provider_token, master_token}) == 3

    maker = async_sessionmaker(db, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        row = (
            await session.execute(select(Order).where(Order.order_no == order_no))
        ).scalar_one()
        assert row.status == OrderStatus.COMPLETED
        assert row.pay_status == PayStatus.PAID
        assert row.master_id == master_id
        assert row.completed_at is not None
        assert row.auto_confirmed is False

        logs = (
            await session.execute(
                select(OrderStatusLog)
                .where(OrderStatusLog.order_id == row.id)
                .order_by(OrderStatusLog.id)
            )
        ).scalars().all()

    # 同一个 order_no 贯穿全程：状态一步都没跳、每一步都留了痕
    assert [log.to_status for log in logs] == [
        OrderStatus.PENDING_PAY,
        OrderStatus.PENDING_DISPATCH,
        OrderStatus.PENDING_ACCEPT,
        OrderStatus.ACCEPTED,
        OrderStatus.IN_SERVICE,
        OrderStatus.PENDING_CONFIRM,
        OrderStatus.COMPLETED,
    ]
    assert [log.operator_type for log in logs] == [
        OperatorType.USER,  # 下单
        OperatorType.SYSTEM,  # mock 支付
        OperatorType.PROVIDER_ADMIN,  # 派单
        OperatorType.MASTER,  # 接单
        OperatorType.MASTER,  # 开工
        OperatorType.MASTER,  # 完工
        OperatorType.USER,  # 客户确认完成
    ]
