"""师傅入驻接口的测试（登记申请 / 我的申请 / 平台审核）。

必测点：

1. **身份只从 token 来**：请求体里出现 user_id / master_id 一律 422；
2. **鉴权**：没 token -> 401；服务商账号 / 平台账号不能登记（403）；
3. **归属不暴露**：目标服务商「不存在」与「不可加入」是同一个 404、同一句话；
4. **重复申请** -> 409；
5. **平台审核**：只有 PLATFORM_ADMIN 能审；通过 -> ACTIVE；驳回 -> 行没了；
6. **请求体不许自报归属**：带 provider_id 字段 -> 422。

集成测试用的数据库是 TEST_DATABASE_URL 指向的独立测试库
（集成 fixture 每次 drop_all + create_all，绝不碰开发库）。
"""
from __future__ import annotations

import os

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.auth import create_access_token
from app.core.database import get_session
from app.main import app
from app.models.base import Base
from app.models.enums import MasterStatus, ProviderStatus, UserRole
from app.models.provider import Master, ServiceProvider
from app.models.user import User

ONBOARDING_URL = "/api/v1/masters/onboarding"
JOINABLE_URL = "/api/v1/masters/joinable-providers"
PLATFORM_MASTERS_URL = "/api/v1/platform/masters"

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


def _auth_header(user_id: int, role: UserRole, provider_id: int | None = None) -> dict[str, str]:
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
    """造数据：一个正常营业的服务商 + 一个待审的 + 各类账号。"""
    maker = async_sessionmaker(db, class_=AsyncSession, expire_on_commit=False)

    async with maker() as session:
        provider_active = ServiceProvider(
            name="甲服务商",
            contact_phone="13900000001",
            status=ProviderStatus.ACTIVE,
        )
        provider_pending = ServiceProvider(
            name="待审服务商",
            contact_phone="13900000002",
            status=ProviderStatus.PENDING,
        )
        session.add_all([provider_active, provider_pending])
        await session.flush()

        plain_user = User(phone="13800000001", nickname="普通用户")
        provider_admin = User(
            phone="13800000002",
            nickname="甲管理员",
            role=UserRole.PROVIDER_ADMIN,
            provider_id=provider_active.id,
        )
        platform_admin = User(
            phone="13800000003",
            nickname="平台管理员",
            role=UserRole.PLATFORM_ADMIN,
        )
        session.add_all([plain_user, provider_admin, platform_admin])
        await session.flush()
        await session.commit()

        return {
            "provider_active": provider_active.id,
            "provider_pending": provider_pending.id,
            "plain_user": plain_user.id,
            "provider_admin": provider_admin.id,
            "platform_admin": platform_admin.id,
        }


@pytest.fixture
async def seeded(db) -> dict[str, int]:
    return await _seed(db)


# =====================================================================
# 登记申请
# =====================================================================


@pytest.mark.integration
async def test_submit_onboarding_success(api_client, seeded) -> None:
    """登记成功 -> 201/200，状态是「待审核」，归属写在申请里。"""
    headers = _auth_header(seeded["plain_user"], UserRole.USER)

    response = await api_client.post(
        ONBOARDING_URL,
        headers=headers,
        json={
            "real_name": "张师傅",
            "target_provider_id": seeded["provider_active"],
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["real_name"] == "张师傅"
    assert body["status"] == "PENDING"
    assert body["provider_id"] == seeded["provider_active"]
    assert body["provider_name"] == "甲服务商"
    assert body["phone"] == "13800000001"


@pytest.mark.integration
async def test_submit_onboarding_requires_token(api_client, seeded) -> None:
    """没 token -> 401。"""
    response = await api_client.post(
        ONBOARDING_URL,
        json={
            "real_name": "张师傅",
            "target_provider_id": seeded["provider_active"],
        },
    )

    assert response.status_code == 401


@pytest.mark.integration
async def test_submit_onboarding_rejects_provider_role(api_client, seeded) -> None:
    """服务商账号 -> 403。"""
    headers = _auth_header(
        seeded["provider_admin"], UserRole.PROVIDER_ADMIN, seeded["provider_active"]
    )

    response = await api_client.post(
        ONBOARDING_URL,
        headers=headers,
        json={
            "real_name": "张师傅",
            "target_provider_id": seeded["provider_active"],
        },
    )

    assert response.status_code == 403


@pytest.mark.integration
async def test_submit_onboarding_rejects_identity_fields(api_client, seeded) -> None:
    """请求体里出现 user_id / master_id / provider_id 一律 422。

    身份与归属都由服务端说了算，客户端自报等于让它自己挑对象。
    """
    headers = _auth_header(seeded["plain_user"], UserRole.USER)

    for extra in (
        {"user_id": seeded["plain_user"]},
        {"master_id": 1},
        {"provider_id": seeded["provider_active"]},
    ):
        payload = {
            "real_name": "张师傅",
            "target_provider_id": seeded["provider_active"],
        }
        payload.update(extra)
        response = await api_client.post(
            ONBOARDING_URL, headers=headers, json=payload
        )
        assert response.status_code == 422, (extra, response.text)


@pytest.mark.integration
async def test_submit_onboarding_unknown_provider_is_404(api_client, seeded) -> None:
    """目标服务商不存在 -> 404（与「不可加入」同构）。"""
    headers = _auth_header(seeded["plain_user"], UserRole.USER)

    responses = []
    for provider_id in (999999, seeded["provider_pending"]):
        response = await api_client.post(
            ONBOARDING_URL,
            headers=headers,
            json={"real_name": "张师傅", "target_provider_id": provider_id},
        )
        responses.append(response)

    assert [response.status_code for response in responses] == [404, 404]
    # 两种失败逐字同构：不告诉调用方「这家存在但没营业」
    assert responses[0].json() == responses[1].json()


@pytest.mark.integration
async def test_submit_onboarding_twice_is_409(api_client, seeded) -> None:
    """重复申请 -> 409。"""
    headers = _auth_header(seeded["plain_user"], UserRole.USER)
    payload = {
        "real_name": "张师傅",
        "target_provider_id": seeded["provider_active"],
    }

    first = await api_client.post(ONBOARDING_URL, headers=headers, json=payload)
    assert first.status_code == 200

    second = await api_client.post(ONBOARDING_URL, headers=headers, json=payload)
    assert second.status_code == 409


# =====================================================================
# 我的申请 / 可加入的服务商
# =====================================================================


@pytest.mark.integration
async def test_get_my_onboarding(api_client, seeded) -> None:
    """查自己的申请：登记之后能查到。"""
    headers = _auth_header(seeded["plain_user"], UserRole.USER)

    missing = await api_client.get(ONBOARDING_URL, headers=headers)
    assert missing.status_code == 404

    await api_client.post(
        ONBOARDING_URL,
        headers=headers,
        json={
            "real_name": "张师傅",
            "target_provider_id": seeded["provider_active"],
        },
    )

    response = await api_client.get(ONBOARDING_URL, headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == "PENDING"


@pytest.mark.integration
async def test_list_joinable_providers(api_client, seeded) -> None:
    """可加入的服务商只有营业中的那些。"""
    headers = _auth_header(seeded["plain_user"], UserRole.USER)

    response = await api_client.get(JOINABLE_URL, headers=headers)

    assert response.status_code == 200
    items = response.json()["items"]
    assert [item["id"] for item in items] == [seeded["provider_active"]]
    # 只暴露 id 与名称
    assert set(items[0]) == {"id", "name"}


# =====================================================================
# 平台审核
# =====================================================================


@pytest.mark.integration
async def test_platform_list_applications(api_client, seeded) -> None:
    """平台侧能列出入驻申请；别的角色看不到。"""
    platform_headers = _auth_header(seeded["platform_admin"], UserRole.PLATFORM_ADMIN)
    user_headers = _auth_header(seeded["plain_user"], UserRole.USER)

    await api_client.post(
        ONBOARDING_URL,
        headers=user_headers,
        json={
            "real_name": "张师傅",
            "target_provider_id": seeded["provider_active"],
        },
    )

    response = await api_client.get(
        PLATFORM_MASTERS_URL, headers=platform_headers, params={"status": "PENDING"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["real_name"] == "张师傅"
    assert body["items"][0]["phone"] == "13800000001"

    forbidden = await api_client.get(PLATFORM_MASTERS_URL, headers=user_headers)
    assert forbidden.status_code == 403


@pytest.mark.integration
async def test_platform_review_approve(api_client, seeded) -> None:
    """审核通过 -> 状态转「已入驻」。"""
    user_headers = _auth_header(seeded["plain_user"], UserRole.USER)
    platform_headers = _auth_header(seeded["platform_admin"], UserRole.PLATFORM_ADMIN)

    submitted = await api_client.post(
        ONBOARDING_URL,
        headers=user_headers,
        json={
            "real_name": "张师傅",
            "target_provider_id": seeded["provider_active"],
        },
    )
    master_id = submitted.json()["id"]

    response = await api_client.post(
        "{}/{}/review".format(PLATFORM_MASTERS_URL, master_id),
        headers=platform_headers,
        json={"decision": "APPROVE"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "ACTIVE"


@pytest.mark.integration
async def test_platform_review_reject(api_client, seeded) -> None:
    """审核驳回 -> 那一行没了（status 为空）。"""
    user_headers = _auth_header(seeded["plain_user"], UserRole.USER)
    platform_headers = _auth_header(seeded["platform_admin"], UserRole.PLATFORM_ADMIN)

    submitted = await api_client.post(
        ONBOARDING_URL,
        headers=user_headers,
        json={
            "real_name": "张师傅",
            "target_provider_id": seeded["provider_active"],
        },
    )
    master_id = submitted.json()["id"]

    response = await api_client.post(
        "{}/{}/review".format(PLATFORM_MASTERS_URL, master_id),
        headers=platform_headers,
        json={"decision": "REJECT", "reason": "资质不齐"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] is None

    # 驳回之后「我的申请」没有了
    missing = await api_client.get(ONBOARDING_URL, headers=user_headers)
    assert missing.status_code == 404


@pytest.mark.integration
async def test_platform_review_requires_platform_admin(api_client, seeded) -> None:
    """服务商账号不能审核 -> 403。"""
    user_headers = _auth_header(seeded["plain_user"], UserRole.USER)
    provider_headers = _auth_header(
        seeded["provider_admin"], UserRole.PROVIDER_ADMIN, seeded["provider_active"]
    )

    submitted = await api_client.post(
        ONBOARDING_URL,
        headers=user_headers,
        json={
            "real_name": "张师傅",
            "target_provider_id": seeded["provider_active"],
        },
    )
    master_id = submitted.json()["id"]

    response = await api_client.post(
        "{}/{}/review".format(PLATFORM_MASTERS_URL, master_id),
        headers=provider_headers,
        json={"decision": "APPROVE"},
    )

    assert response.status_code == 403


@pytest.mark.integration
async def test_platform_review_unknown_is_404(api_client, seeded) -> None:
    """审核不存在的申请 -> 404。"""
    platform_headers = _auth_header(seeded["platform_admin"], UserRole.PLATFORM_ADMIN)

    response = await api_client.post(
        "{}/999999/review".format(PLATFORM_MASTERS_URL),
        headers=platform_headers,
        json={"decision": "APPROVE"},
    )

    assert response.status_code == 404


@pytest.mark.integration
async def test_platform_review_rejects_bad_decision(api_client, seeded) -> None:
    """审核结论非法 -> 422（窄枚举）。"""
    platform_headers = _auth_header(seeded["platform_admin"], UserRole.PLATFORM_ADMIN)

    response = await api_client.post(
        "{}/1/review".format(PLATFORM_MASTERS_URL),
        headers=platform_headers,
        json={"decision": "MAYBE"},
    )

    assert response.status_code == 422
