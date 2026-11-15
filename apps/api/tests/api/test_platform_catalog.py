"""平台侧目录管理接口的测试（/api/v1/platform/categories 与 /items）。

必测点：

1. **鉴权**：不是平台侧角色（普通用户 / 服务商账号）-> 403；没 token -> 401；
   PLATFORM_OPS 能进（平台运营也管目录）。
2. **改价必须留痕**（R3）：base_price 变了 -> audit_log 里有 old / new 值。
3. **条件 UPDATE**：客户端带的 expected_status 与库里对不上 -> 409，
   而且那一行一个字节都没变。
4. **品类树**：含子品类；**含已停用的**（平台要能看见停用的东西才能重新启用）。
5. **不存在**：改 / 建到不存在的对象上 -> 404。

集成测试用的数据库是 TEST_DATABASE_URL 指向的独立测试库
（集成 fixture 每次 drop_all + create_all，绝不碰开发库）。
"""
from __future__ import annotations

import os
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.auth import create_access_token
from app.core.database import get_session
from app.main import app
from app.models.audit_log import AuditLog
from app.models.base import Base
from app.models.catalog import ServiceCategory, ServiceItem
from app.models.enums import CatalogStatus, OperatorType, UserRole
from app.models.provider import ServiceProvider
from app.models.user import User

CATEGORIES_URL = "/api/v1/platform/categories"
ITEMS_URL = "/api/v1/platform/items"

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
    """造平台账号、服务商账号、一棵品类树（父子两级）与一个服务项。"""
    maker = async_sessionmaker(db, class_=AsyncSession, expire_on_commit=False)

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
        session.add_all([platform_admin, platform_ops, plain_user])
        await session.flush()

        provider = ServiceProvider(name="甲服务商", contact_phone="13900000001")
        session.add(provider)
        await session.flush()

        # 服务商账号必须带 provider_id（数据库 CHECK 约束强制）
        provider_admin = User(
            phone="13800000001",
            nickname="服务商管理员",
            role=UserRole.PROVIDER_ADMIN,
            provider_id=provider.id,
        )
        session.add(provider_admin)
        await session.flush()

        parent = ServiceCategory(
            name="家庭保洁", parent_id=None, sort_order=1, status=CatalogStatus.ACTIVE
        )
        session.add(parent)
        await session.flush()

        child = ServiceCategory(
            name="日常保洁",
            parent_id=parent.id,
            sort_order=2,
            status=CatalogStatus.ACTIVE,
        )
        # 一个已停用的品类：平台侧要看得见停用的东西
        disabled = ServiceCategory(
            name="已下架品类",
            parent_id=None,
            sort_order=9,
            status=CatalogStatus.INACTIVE,
        )
        session.add_all([child, disabled])
        await session.flush()

        item = ServiceItem(
            category_id=parent.id,
            name="日常保洁服务",
            base_price=Decimal("100.00"),
            duration_min=60,
            status=CatalogStatus.ACTIVE,
        )
        session.add(item)
        await session.flush()
        await session.commit()

        return {
            "platform_admin": platform_admin.id,
            "platform_ops": platform_ops.id,
            "plain_user": plain_user.id,
            "provider_admin": provider_admin.id,
            "provider": provider.id,
            "parent": parent.id,
            "child": child.id,
            "disabled": disabled.id,
            "item": item.id,
        }


@pytest.fixture
async def seeded(db) -> dict[str, int]:
    return await _seed(db)


def _platform_headers(seeded: dict[str, int]) -> dict[str, str]:
    return _auth_header(seeded["platform_admin"], UserRole.PLATFORM_ADMIN, None)


async def _audit_logs(db, target_type: str, target_id: int) -> list[AuditLog]:
    """读某个对象的全部审计记录。"""
    maker = async_sessionmaker(db, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        logs = (
            (
                await session.execute(
                    select(AuditLog).where(
                        AuditLog.target_type == target_type,
                        AuditLog.target_id == target_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        return list(logs)


# =====================================================================
# 鉴权
# =====================================================================


@pytest.mark.integration
async def test_catalog_requires_authentication(api_client, seeded) -> None:
    """没有 token -> 401。"""
    response = await api_client.get(CATEGORIES_URL)
    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}


@pytest.mark.integration
async def test_list_categories_rejects_plain_user(api_client, seeded) -> None:
    """普通用户 -> 403。"""
    headers = _auth_header(seeded["plain_user"], UserRole.USER, None)
    response = await api_client.get(CATEGORIES_URL, headers=headers)
    assert response.status_code == 403
    assert response.json() == {"detail": "Forbidden"}


@pytest.mark.integration
async def test_catalog_rejects_provider_admin(api_client, seeded) -> None:
    """服务商账号 -> 403：目录是平台侧管的。"""
    headers = _auth_header(
        seeded["provider_admin"], UserRole.PROVIDER_ADMIN, seeded["provider"]
    )
    assert (await api_client.get(CATEGORIES_URL, headers=headers)).status_code == 403
    assert (
        await api_client.post(
            CATEGORIES_URL, json={"name": "野品类"}, headers=headers
        )
    ).status_code == 403
    assert (
        await api_client.post(
            ITEMS_URL,
            json={
                "category_id": seeded["parent"],
                "name": "野服务项",
                "base_price": "1.00",
                "duration_min": 30,
            },
            headers=headers,
        )
    ).status_code == 403


@pytest.mark.integration
async def test_catalog_allows_platform_ops(api_client, seeded) -> None:
    """平台运营（PLATFORM_OPS）也能管目录。"""
    headers = _auth_header(seeded["platform_ops"], UserRole.PLATFORM_OPS, None)
    response = await api_client.get(CATEGORIES_URL, headers=headers)
    assert response.status_code == 200


# =====================================================================
# 品类树
# =====================================================================


@pytest.mark.integration
async def test_list_categories_returns_tree_with_children(api_client, seeded) -> None:
    """品类树：一级品类带着自己的子树。"""
    headers = _platform_headers(seeded)
    response = await api_client.get(CATEGORIES_URL, headers=headers)
    assert response.status_code == 200
    body = response.json()

    by_name = {node["name"]: node for node in body}
    assert "家庭保洁" in by_name
    parent = by_name["家庭保洁"]
    assert parent["parent_id"] is None
    assert [child["name"] for child in parent["children"]] == ["日常保洁"]


@pytest.mark.integration
async def test_list_categories_includes_inactive(api_client, seeded) -> None:
    """已停用的品类也要出现：平台要能看见才能重新启用。"""
    headers = _platform_headers(seeded)
    response = await api_client.get(CATEGORIES_URL, headers=headers)
    assert response.status_code == 200
    names = {node["name"] for node in response.json()}
    assert "已下架品类" in names


@pytest.mark.integration
async def test_list_categories_includes_items(api_client, seeded) -> None:
    """品类节点上带着本品类下的服务项。"""
    headers = _platform_headers(seeded)
    response = await api_client.get(CATEGORIES_URL, headers=headers)
    assert response.status_code == 200
    parent = next(
        node for node in response.json() if node["name"] == "家庭保洁"
    )
    assert len(parent["items"]) == 1
    assert parent["items"][0]["name"] == "日常保洁服务"
    assert Decimal(parent["items"][0]["base_price"]) == Decimal("100.00")


# =====================================================================
# 品类：建 / 改
# =====================================================================


@pytest.mark.integration
async def test_create_category_starts_active_and_writes_audit(
    api_client, seeded, db
) -> None:
    """新建品类：初始状态启用，audit_log 有记录。"""
    headers = _platform_headers(seeded)
    response = await api_client.post(
        CATEGORIES_URL,
        json={"name": "月嫂服务", "sort_order": 5},
        headers=headers,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "月嫂服务"
    assert body["status"] == "ACTIVE"
    assert body["parent_id"] is None
    assert body["sort_order"] == 5

    logs = await _audit_logs(db, "service_category", body["id"])
    assert [log.field_name for log in logs] == ["created"]
    assert logs[0].new_value == "月嫂服务"
    assert logs[0].operator_type == OperatorType.PLATFORM_ADMIN
    assert logs[0].operator_id == seeded["platform_admin"]


@pytest.mark.integration
async def test_create_category_with_parent(api_client, seeded) -> None:
    """建子品类：parent_id 指向存在的品类。"""
    headers = _platform_headers(seeded)
    response = await api_client.post(
        CATEGORIES_URL,
        json={"name": "深度保洁", "parent_id": seeded["parent"]},
        headers=headers,
    )
    assert response.status_code == 201
    assert response.json()["parent_id"] == seeded["parent"]


@pytest.mark.integration
async def test_create_category_with_missing_parent_returns_404(
    api_client, seeded
) -> None:
    """父品类不存在 -> 404。"""
    headers = _platform_headers(seeded)
    response = await api_client.post(
        CATEGORIES_URL,
        json={"name": "孤儿品类", "parent_id": seeded["parent"] + 100000},
        headers=headers,
    )
    assert response.status_code == 404


@pytest.mark.integration
async def test_update_category_writes_audit_per_changed_field(
    api_client, seeded, db
) -> None:
    """改品类：每个真变了的字段一条 audit_log，old / new 值都有。"""
    headers = _platform_headers(seeded)
    response = await api_client.patch(
        "{}/{}".format(CATEGORIES_URL, seeded["parent"]),
        json={"name": "家庭保洁新名", "status": "INACTIVE"},
        headers=headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "家庭保洁新名"
    assert body["status"] == "INACTIVE"

    logs = await _audit_logs(db, "service_category", seeded["parent"])
    by_field = {log.field_name: log for log in logs}
    assert set(by_field) == {"name", "status"}
    assert by_field["name"].old_value == "家庭保洁"
    assert by_field["name"].new_value == "家庭保洁新名"
    assert by_field["status"].old_value == "ACTIVE"
    assert by_field["status"].new_value == "INACTIVE"
    for log in logs:
        assert log.operator_type == OperatorType.PLATFORM_ADMIN
        assert log.operator_id == seeded["platform_admin"]
        # 平台侧操作不涉及具体服务商
        assert log.provider_id is None


@pytest.mark.integration
async def test_update_category_unchanged_field_writes_no_audit(
    api_client, seeded, db
) -> None:
    """没变的字段不留痕（否则审计日志会被噪声淹掉）。"""
    headers = _platform_headers(seeded)
    response = await api_client.patch(
        "{}/{}".format(CATEGORIES_URL, seeded["parent"]),
        json={"name": "家庭保洁", "sort_order": 1},
        headers=headers,
    )
    assert response.status_code == 200
    assert await _audit_logs(db, "service_category", seeded["parent"]) == []


@pytest.mark.integration
async def test_update_category_conflict_returns_409(api_client, seeded, db) -> None:
    """expected_status 与库里的对不上 -> 409，且那一行没变。"""
    headers = _platform_headers(seeded)
    response = await api_client.patch(
        "{}/{}".format(CATEGORIES_URL, seeded["parent"]),
        json={"name": "被别人改过", "expected_status": "INACTIVE"},
        headers=headers,
    )
    assert response.status_code == 409

    maker = async_sessionmaker(db, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        category = (
            await session.execute(
                select(ServiceCategory).where(ServiceCategory.id == seeded["parent"])
            )
        ).scalar_one()
        assert category.name == "家庭保洁"
        assert category.status == CatalogStatus.ACTIVE


@pytest.mark.integration
async def test_update_category_missing_returns_404(api_client, seeded) -> None:
    """品类不存在 -> 404。"""
    headers = _platform_headers(seeded)
    response = await api_client.patch(
        "{}/{}".format(CATEGORIES_URL, seeded["parent"] + 100000),
        json={"name": "无中生有"},
        headers=headers,
    )
    assert response.status_code == 404


@pytest.mark.integration
async def test_update_category_rejects_empty_change(api_client, seeded) -> None:
    """三个字段都不传 -> 422（空操作没有意义）。"""
    headers = _platform_headers(seeded)
    response = await api_client.patch(
        "{}/{}".format(CATEGORIES_URL, seeded["parent"]),
        json={"expected_status": "ACTIVE"},
        headers=headers,
    )
    assert response.status_code == 422


@pytest.mark.integration
async def test_update_category_rejects_operator_in_body(api_client, seeded) -> None:
    """请求体里带 operator -> 422（身份只从 token 来）。"""
    headers = _platform_headers(seeded)
    response = await api_client.patch(
        "{}/{}".format(CATEGORIES_URL, seeded["parent"]),
        json={"name": "改名", "operator_id": 999},
        headers=headers,
    )
    assert response.status_code == 422


# =====================================================================
# 服务项：建 / 改（含改价留痕）
# =====================================================================


@pytest.mark.integration
async def test_create_item_starts_active_and_writes_audit(
    api_client, seeded, db
) -> None:
    """新建服务项：初始状态启用，audit_log 有记录。"""
    headers = _platform_headers(seeded)
    response = await api_client.post(
        ITEMS_URL,
        json={
            "category_id": seeded["parent"],
            "name": "深度保洁服务",
            "base_price": "188.00",
            "duration_min": 120,
        },
        headers=headers,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "深度保洁服务"
    assert body["status"] == "ACTIVE"
    assert Decimal(body["base_price"]) == Decimal("188.00")
    assert body["duration_min"] == 120

    logs = await _audit_logs(db, "service_item", body["id"])
    assert [log.field_name for log in logs] == ["created"]


@pytest.mark.integration
async def test_create_item_with_missing_category_returns_404(
    api_client, seeded
) -> None:
    """品类不存在 -> 404（不能把服务项挂在不存在的品类下）。"""
    headers = _platform_headers(seeded)
    response = await api_client.post(
        ITEMS_URL,
        json={
            "category_id": seeded["parent"] + 100000,
            "name": "孤儿服务项",
            "base_price": "10.00",
            "duration_min": 30,
        },
        headers=headers,
    )
    assert response.status_code == 404


@pytest.mark.integration
async def test_update_item_price_writes_audit_with_old_and_new(
    api_client, seeded, db
) -> None:
    """改价 -> audit_log 里有 old / new 值（R3 要追的就是这个）。"""
    headers = _platform_headers(seeded)
    response = await api_client.patch(
        "{}/{}".format(ITEMS_URL, seeded["item"]),
        json={"base_price": "150.50"},
        headers=headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert Decimal(body["base_price"]) == Decimal("150.50")

    logs = await _audit_logs(db, "service_item", seeded["item"])
    price_logs = [log for log in logs if log.field_name == "base_price"]
    assert len(price_logs) == 1
    log = price_logs[0]
    assert log.old_value == "100.00"
    assert log.new_value == "150.50"
    assert log.operator_type == OperatorType.PLATFORM_ADMIN
    assert log.operator_id == seeded["platform_admin"]
    assert log.provider_id is None


@pytest.mark.integration
async def test_update_item_records_platform_ops_as_operator(
    api_client, seeded, db
) -> None:
    """平台运营改价 -> operator_type 记 PLATFORM_OPS（不冒充电商管理员）。"""
    headers = _auth_header(seeded["platform_ops"], UserRole.PLATFORM_OPS, None)
    response = await api_client.patch(
        "{}/{}".format(ITEMS_URL, seeded["item"]),
        json={"base_price": "120.00"},
        headers=headers,
    )
    assert response.status_code == 200

    logs = await _audit_logs(db, "service_item", seeded["item"])
    price_logs = [log for log in logs if log.field_name == "base_price"]
    assert len(price_logs) == 1
    assert price_logs[0].operator_type == OperatorType.PLATFORM_OPS
    assert price_logs[0].operator_id == seeded["platform_ops"]


@pytest.mark.integration
async def test_update_item_conflict_returns_409(api_client, seeded, db) -> None:
    """expected_status 对不上 -> 409，而且价没被改。"""
    headers = _platform_headers(seeded)
    response = await api_client.patch(
        "{}/{}".format(ITEMS_URL, seeded["item"]),
        json={"base_price": "999.00", "expected_status": "INACTIVE"},
        headers=headers,
    )
    assert response.status_code == 409

    maker = async_sessionmaker(db, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        item = (
            await session.execute(
                select(ServiceItem).where(ServiceItem.id == seeded["item"])
            )
        ).scalar_one()
        assert item.base_price == Decimal("100.00")
    assert await _audit_logs(db, "service_item", seeded["item"]) == []


@pytest.mark.integration
async def test_update_item_missing_returns_404(api_client, seeded) -> None:
    """服务项不存在 -> 404。"""
    headers = _platform_headers(seeded)
    response = await api_client.patch(
        "{}/{}".format(ITEMS_URL, seeded["item"] + 100000),
        json={"base_price": "1.00"},
        headers=headers,
    )
    assert response.status_code == 404


@pytest.mark.integration
async def test_update_item_rejects_empty_change(api_client, seeded) -> None:
    """一个字段都不改 -> 422。"""
    headers = _platform_headers(seeded)
    response = await api_client.patch(
        "{}/{}".format(ITEMS_URL, seeded["item"]),
        json={"expected_status": "ACTIVE"},
        headers=headers,
    )
    assert response.status_code == 422


@pytest.mark.integration
async def test_update_item_rejects_negative_price(api_client, seeded) -> None:
    """负价格 -> 422（数据库 CHECK 约束之外，接口层先挡住）。"""
    headers = _platform_headers(seeded)
    response = await api_client.patch(
        "{}/{}".format(ITEMS_URL, seeded["item"]),
        json={"base_price": "-1.00"},
        headers=headers,
    )
    assert response.status_code == 422
