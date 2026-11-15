"""单查服务项接口的测试（GET /api/v1/items/{item_id}）。

必测点：**单查服务项返回正确的名称 / 价格 / 时长**（卡片要求）。

另外补两条边界：服务项不存在 -> 404；服务项已停用 -> 404
（「不存在」与「已停用」共用一句话，不泄露目录状态）。
"""
from __future__ import annotations

import os
import re
from decimal import Decimal

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.auth import create_access_token
from app.core.database import get_session
from app.main import app
from app.models.base import Base
from app.models.catalog import ServiceCategory, ServiceItem
from app.models.enums import CatalogStatus, UserRole

ITEMS_URL = "/api/v1/items"

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

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
    """一个启用中的服务项（10）和一个已停用的服务项（12）。"""
    maker = async_sessionmaker(db, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        session.add(ServiceCategory(id=1, name="家庭保洁", parent_id=None, sort_order=1))
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
                id=12,
                category_id=1,
                name="已下架服务项",
                base_price=Decimal("150.00"),
                duration_min=90,
                status=CatalogStatus.INACTIVE,
            )
        )
        await session.commit()
    return {"active_item": 10, "inactive_item": 12}


# =====================================================================
# 必测：单查服务项返回正确
# =====================================================================


@pytest.mark.integration
async def test_get_item_returns_correct_fields(api_client, seeded) -> None:
    """名称 / 基准价 / 时长都对得上。"""
    response = await api_client.get(
        "{}/{}".format(ITEMS_URL, seeded["active_item"]),
        headers=_auth_header(1),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == seeded["active_item"]
    assert body["name"] == "日常保洁"
    assert Decimal(str(body["base_price"])) == Decimal("100.00")
    assert body["duration_min"] == 60
    assert body["category_id"] == 1


@pytest.mark.integration
async def test_get_unknown_item_returns_404(api_client, seeded) -> None:
    """服务项不存在 -> 404。"""
    response = await api_client.get(
        "{}/999999".format(ITEMS_URL), headers=_auth_header(1)
    )
    assert response.status_code == 404


@pytest.mark.integration
async def test_get_inactive_item_is_isomorphic_to_missing(api_client, seeded) -> None:
    """已停用与不存在返回**完全一样**的 404（不泄露目录状态）。"""
    inactive = await api_client.get(
        "{}/{}".format(ITEMS_URL, seeded["inactive_item"]),
        headers=_auth_header(1),
    )
    missing = await api_client.get(
        "{}/999999".format(ITEMS_URL), headers=_auth_header(1)
    )
    assert inactive.status_code == 404
    assert missing.status_code == 404
    assert DIGITS.sub("#", inactive.json()["detail"]) == DIGITS.sub(
        "#", missing.json()["detail"]
    )


@pytest.mark.integration
async def test_get_item_requires_authentication(api_client, seeded) -> None:
    """没有 token -> 401。"""
    response = await api_client.get(
        "{}/{}".format(ITEMS_URL, seeded["active_item"])
    )
    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}
