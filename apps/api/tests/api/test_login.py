"""登录接口的测试（手机号 + 验证码）。

必测点：

1. **验证码不对 -> 401**（卡片要求）；
2. **验证码对 -> 200，给的 token 能直接用**（拿它调受保护接口不 401）；
3. **手机号没注册过 -> 自动建号**（C 端「登录即注册」）；
4. **账号被禁用 -> 403**。

验证码是 MVP 占位（settings.login_sms_code，默认 123456），不接短信网关。
"""
from __future__ import annotations

import os

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import get_session
from app.main import app
from app.models.base import Base
from app.models.enums import UserStatus
from app.models.user import User

LOGIN_URL = "/api/v1/auth/login"
ADDRESSES_URL = "/api/v1/addresses"

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

# 与 app.core.config.Settings.login_sms_code 的默认值一致
VALID_CODE = "123456"


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
    """一个正常用户 + 一个被禁用的用户。

    **不显式指定 id**：让数据库序列自己分配。显式写 id 会让序列停在 1，
    登录时自动建号拿到的 id 就会撞上已有的行。
    """
    maker = async_sessionmaker(db, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        active = User(phone="13800000001", nickname="体验用户")
        disabled = User(
            phone="13800000002",
            nickname="已禁用用户",
            status=UserStatus.DISABLED,
        )
        session.add_all([active, disabled])
        await session.flush()
        await session.commit()
        return {"active_user": active.id, "disabled_user": disabled.id}


# =====================================================================
# 必测 1：验证码不对 -> 401
# =====================================================================


@pytest.mark.integration
async def test_login_with_wrong_code_returns_401(api_client, seeded) -> None:
    """验证码写错 -> 401。"""
    response = await api_client.post(
        LOGIN_URL, json={"phone": "13800000001", "code": "000000"}
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "验证码错误或已过期"


@pytest.mark.integration
async def test_login_with_wrong_code_does_not_create_user(
    api_client, seeded, db
) -> None:
    """验证码不对时连账号都不建（没通过校验就不该留下痕迹）。"""
    await api_client.post(
        LOGIN_URL, json={"phone": "13900000009", "code": "000000"}
    )

    maker = async_sessionmaker(db, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        count = (
            await session.execute(
                select(func.count()).select_from(User).where(User.phone == "13900000009")
            )
        ).scalar_one()
    assert count == 0, "验证码校验没过就建了账号"

    # 验证码对了才建号
    response = await api_client.post(
        LOGIN_URL, json={"phone": "13900000009", "code": VALID_CODE}
    )
    assert response.status_code == 200


# =====================================================================
# 验证码对 -> 200
# =====================================================================


@pytest.mark.integration
async def test_login_with_correct_code_returns_token(api_client, seeded) -> None:
    """验证码对 -> 200，返回 token 和用户信息。"""
    response = await api_client.post(
        LOGIN_URL, json={"phone": "13800000001", "code": VALID_CODE}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["user"]["id"] == seeded["active_user"]
    assert body["user"]["phone"] == "13800000001"
    assert body["user"]["nickname"] == "体验用户"


@pytest.mark.integration
async def test_login_token_can_call_protected_endpoint(api_client, seeded) -> None:
    """登录给的 token 能直接调受保护接口（不是摆设）。"""
    login = await api_client.post(
        LOGIN_URL, json={"phone": "13800000001", "code": VALID_CODE}
    )
    token = login.json()["access_token"]

    response = await api_client.get(
        ADDRESSES_URL, headers={"Authorization": "Bearer {}".format(token)}
    )
    assert response.status_code == 200
    assert response.json() == []


# =====================================================================
# 登录即注册
# =====================================================================


@pytest.mark.integration
async def test_login_with_unknown_phone_creates_user(api_client, seeded) -> None:
    """没注册过的手机号 -> 自动建号并登录成功。"""
    response = await api_client.post(
        LOGIN_URL, json={"phone": "13900000009", "code": VALID_CODE}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["user"]["phone"] == "13900000009"
    # 新建的用户是普通用户角色
    assert body["user"]["id"] > 0


@pytest.mark.integration
async def test_login_twice_returns_same_user(api_client, seeded) -> None:
    """同一个手机号登录两次，拿到的是同一个用户（不重复建号）。"""
    first = await api_client.post(
        LOGIN_URL, json={"phone": "13900000009", "code": VALID_CODE}
    )
    second = await api_client.post(
        LOGIN_URL, json={"phone": "13900000009", "code": VALID_CODE}
    )
    assert first.json()["user"]["id"] == second.json()["user"]["id"]


# =====================================================================
# 禁用账号
# =====================================================================


@pytest.mark.integration
async def test_login_with_disabled_user_returns_403(api_client, seeded) -> None:
    """账号被禁用 -> 403（验证码对也不给登）。"""
    response = await api_client.post(
        LOGIN_URL, json={"phone": "13800000002", "code": VALID_CODE}
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "账号已被禁用"


# =====================================================================
# 入参边界
# =====================================================================


@pytest.mark.integration
async def test_login_rejects_extra_fields(api_client, seeded) -> None:
    """请求体里多带字段 -> 422（extra=forbid）。"""
    response = await api_client.post(
        LOGIN_URL,
        json={"phone": "13800000001", "code": VALID_CODE, "user_id": 999},
    )
    assert response.status_code == 422


@pytest.mark.integration
async def test_login_does_not_require_token(api_client, seeded) -> None:
    """登录接口本身不需要 token（否则拿不到 token）。"""
    response = await api_client.post(
        LOGIN_URL, json={"phone": "13800000001", "code": VALID_CODE}
    )
    assert response.status_code == 200
