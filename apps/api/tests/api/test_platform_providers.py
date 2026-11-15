"""平台侧服务商管理接口的测试（/api/v1/platform/providers）。

必测点：

1. **鉴权**：不是 PLATFORM_ADMIN -> 403（文案与别处的越权失败一致）；
   没 token -> 401。
2. **改状态用条件 UPDATE**：当前状态不允许这次流转 -> 409，
   而不是把状态硬改过去。
3. **建服务商 + 建管理员**：初始状态是「待审核」；管理员账号的
   role / provider_id 由服务端填；audit_log 有记录（R3）。
4. **手机号唯一**：手机号已被占用 -> 409「手机号已注册」。

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
from app.models.enums import OperatorType, ProviderStatus, UserRole
from app.models.provider import ServiceProvider
from app.models.user import User

PROVIDERS_URL = "/api/v1/platform/providers"

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
    """造平台管理员、普通用户、服务商管理员，以及三个不同状态的服务商。

    **不显式指定 id**：让数据库序列自己分配（与 test_provider_masters 同理）。
    """
    maker = async_sessionmaker(db, class_=AsyncSession, expire_on_commit=False)

    async with maker() as session:
        platform_admin = User(
            phone="13700000001",
            nickname="平台管理员",
            role=UserRole.PLATFORM_ADMIN,
            provider_id=None,
        )
        plain_user = User(phone="13700000002", nickname="普通用户")
        session.add_all([platform_admin, plain_user])
        await session.flush()

        pending = ServiceProvider(
            name="待审核服务商",
            contact_phone="13900000001",
            commission_rate=Decimal("0.1500"),
            status=ProviderStatus.PENDING,
        )
        active = ServiceProvider(
            name="营业中服务商",
            contact_phone="13900000002",
            commission_rate=Decimal("0.2000"),
            status=ProviderStatus.ACTIVE,
        )
        frozen = ServiceProvider(
            name="已冻结服务商",
            contact_phone="13900000003",
            commission_rate=Decimal("0.1000"),
            status=ProviderStatus.FROZEN,
        )
        session.add_all([pending, active, frozen])
        await session.flush()

        # PROVIDER_ADMIN 必须带 provider_id（数据库 CHECK 约束强制），
        # 所以这个账号要等服务商建出来才能建。
        provider_admin = User(
            phone="13700000003",
            nickname="服务商管理员",
            role=UserRole.PROVIDER_ADMIN,
            provider_id=active.id,
        )
        session.add(provider_admin)
        await session.flush()
        await session.commit()

        return {
            "platform_admin": platform_admin.id,
            "plain_user": plain_user.id,
            "provider_admin": provider_admin.id,
            "pending": pending.id,
            "active": active.id,
            "frozen": frozen.id,
        }


@pytest.fixture
async def seeded(db) -> dict[str, int]:
    return await _seed(db)


def _platform_headers(seeded: dict[str, int]) -> dict[str, str]:
    return _auth_header(seeded["platform_admin"], UserRole.PLATFORM_ADMIN, None)


# =====================================================================
# 鉴权：只有 PLATFORM_ADMIN 能用
# =====================================================================


@pytest.mark.integration
async def test_list_providers_rejects_non_platform_admin(api_client, seeded) -> None:
    """普通用户 -> 403（文案与别处的越权失败一致）。"""
    headers = _auth_header(seeded["plain_user"], UserRole.USER, None)
    response = await api_client.get(PROVIDERS_URL, headers=headers)
    assert response.status_code == 403
    assert response.json() == {"detail": "Forbidden"}


@pytest.mark.integration
async def test_list_providers_rejects_provider_admin(api_client, seeded) -> None:
    """服务商管理员 -> 403：平台侧接口与服务商侧不是一回事。"""
    headers = _auth_header(
        seeded["provider_admin"], UserRole.PROVIDER_ADMIN, seeded["active"]
    )
    response = await api_client.get(PROVIDERS_URL, headers=headers)
    assert response.status_code == 403
    assert response.json() == {"detail": "Forbidden"}


@pytest.mark.integration
async def test_create_provider_rejects_non_platform_admin(api_client, seeded) -> None:
    """建档 -> 403（不是平台管理员不许建）。"""
    headers = _auth_header(seeded["plain_user"], UserRole.USER, None)
    response = await api_client.post(
        PROVIDERS_URL,
        json={"name": "野服务商", "contact_phone": "13900000009", "commission_rate": "0.1"},
        headers=headers,
    )
    assert response.status_code == 403


@pytest.mark.integration
async def test_patch_provider_status_rejects_non_platform_admin(api_client, seeded) -> None:
    """改状态 -> 403。"""
    headers = _auth_header(seeded["plain_user"], UserRole.USER, None)
    response = await api_client.patch(
        "{}/{}".format(PROVIDERS_URL, seeded["pending"]),
        json={"status": "ACTIVE"},
        headers=headers,
    )
    assert response.status_code == 403


@pytest.mark.integration
async def test_create_provider_admin_rejects_non_platform_admin(api_client, seeded) -> None:
    """建管理员账号 -> 403。"""
    headers = _auth_header(seeded["plain_user"], UserRole.USER, None)
    response = await api_client.post(
        "{}/{}/admin".format(PROVIDERS_URL, seeded["active"]),
        json={"phone": "13900000009"},
        headers=headers,
    )
    assert response.status_code == 403


@pytest.mark.integration
async def test_platform_endpoints_require_authentication(api_client, seeded) -> None:
    """没有 token -> 401。"""
    response = await api_client.get(PROVIDERS_URL)
    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}


# =====================================================================
# 条件 UPDATE：状态冲突 -> 409
# =====================================================================


@pytest.mark.integration
async def test_patch_status_conflict_returns_409(api_client, seeded) -> None:
    """当前状态不允许这次流转 -> 409。

    已冻结（ACTIVE -> FROZEN 之后）再冻一次：条件 UPDATE 的谓词
    （status = ACTIVE）不成立，rowcount == 0 -> 409。
    """
    headers = _platform_headers(seeded)

    first = await api_client.patch(
        "{}/{}".format(PROVIDERS_URL, seeded["active"]),
        json={"status": "FROZEN"},
        headers=headers,
    )
    assert first.status_code == 200

    second = await api_client.patch(
        "{}/{}".format(PROVIDERS_URL, seeded["active"]),
        json={"status": "FROZEN"},
        headers=headers,
    )
    assert second.status_code == 409


@pytest.mark.integration
async def test_patch_status_conflict_does_not_change_the_row(
    api_client, seeded, db
) -> None:
    """状态冲突 -> 409，而且那一行的状态一个字节都没变。"""
    headers = _platform_headers(seeded)

    await api_client.patch(
        "{}/{}".format(PROVIDERS_URL, seeded["active"]),
        json={"status": "FROZEN"},
        headers=headers,
    )
    conflict = await api_client.patch(
        "{}/{}".format(PROVIDERS_URL, seeded["active"]),
        json={"status": "FROZEN"},
        headers=headers,
    )
    assert conflict.status_code == 409

    maker = async_sessionmaker(db, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        provider = (
            await session.execute(
                select(ServiceProvider).where(ServiceProvider.id == seeded["active"])
            )
        ).scalar_one()
        assert provider.status == ProviderStatus.FROZEN


@pytest.mark.integration
async def test_patch_pending_to_frozen_returns_409(api_client, seeded) -> None:
    """待审核不能直接冻结 -> 409（冻结只允许从营业中改）。"""
    headers = _platform_headers(seeded)
    response = await api_client.patch(
        "{}/{}".format(PROVIDERS_URL, seeded["pending"]),
        json={"status": "FROZEN"},
        headers=headers,
    )
    assert response.status_code == 409


@pytest.mark.integration
async def test_patch_status_writes_audit_log(api_client, seeded, db) -> None:
    """改状态 -> audit_log 留痕：谁改的、把谁、从什么改成什么。"""
    headers = _platform_headers(seeded)
    response = await api_client.patch(
        "{}/{}".format(PROVIDERS_URL, seeded["pending"]),
        json={"status": "ACTIVE"},
        headers=headers,
    )
    assert response.status_code == 200

    maker = async_sessionmaker(db, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        logs = (
            (
                await session.execute(
                    select(AuditLog).where(
                        AuditLog.target_type == "service_provider",
                        AuditLog.target_id == seeded["pending"],
                        AuditLog.field_name == "status",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(logs) == 1
        log = logs[0]
        assert log.old_value == "PENDING"
        assert log.new_value == "ACTIVE"
        assert log.operator_type == OperatorType.PLATFORM_ADMIN
        assert log.operator_id == seeded["platform_admin"]
        assert log.provider_id == seeded["pending"]


@pytest.mark.integration
async def test_patch_status_accepts_unfreeze(api_client, seeded) -> None:
    """解冻：FROZEN -> ACTIVE。"""
    headers = _platform_headers(seeded)
    response = await api_client.patch(
        "{}/{}".format(PROVIDERS_URL, seeded["frozen"]),
        json={"status": "ACTIVE"},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ACTIVE"


@pytest.mark.integration
async def test_patch_missing_provider_returns_404(api_client, seeded) -> None:
    """服务商不存在 -> 404（不是 409：那是状态冲突）。"""
    headers = _platform_headers(seeded)
    response = await api_client.patch(
        "{}/{}".format(PROVIDERS_URL, seeded["pending"] + 100000),
        json={"status": "ACTIVE"},
        headers=headers,
    )
    assert response.status_code == 404


@pytest.mark.integration
async def test_patch_status_rejects_pending_target(api_client, seeded) -> None:
    """目标状态 PENDING 不许设置 -> 422（窄枚举拦在接口层）。"""
    headers = _platform_headers(seeded)
    response = await api_client.patch(
        "{}/{}".format(PROVIDERS_URL, seeded["active"]),
        json={"status": "PENDING"},
        headers=headers,
    )
    assert response.status_code == 422


@pytest.mark.integration
async def test_patch_status_rejects_provider_id_in_body(api_client, seeded) -> None:
    """请求体里带 provider_id -> 422（归属由路径与 token 决定）。"""
    headers = _platform_headers(seeded)
    response = await api_client.patch(
        "{}/{}".format(PROVIDERS_URL, seeded["active"]),
        json={"status": "FROZEN", "provider_id": seeded["pending"]},
        headers=headers,
    )
    assert response.status_code == 422


# =====================================================================
# 建档 + 建管理员
# =====================================================================


@pytest.mark.integration
async def test_create_provider_starts_as_pending(api_client, seeded) -> None:
    """新建的服务商初始状态是「待审核」（PENDING），不由请求体决定。"""
    headers = _platform_headers(seeded)
    response = await api_client.post(
        PROVIDERS_URL,
        json={
            "name": "丁服务商",
            "contact_phone": "13900000009",
            "commission_rate": "0.18",
        },
        headers=headers,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "丁服务商"
    assert body["contact_phone"] == "13900000009"
    assert body["status"] == "PENDING"
    assert Decimal(body["commission_rate"]) == Decimal("0.18")


@pytest.mark.integration
async def test_create_provider_rejects_out_of_range_commission_rate(
    api_client, seeded
) -> None:
    """佣金比例必须在 0~1 -> 422。"""
    headers = _platform_headers(seeded)
    response = await api_client.post(
        PROVIDERS_URL,
        json={
            "name": "越界服务商",
            "contact_phone": "13900000009",
            "commission_rate": "1.5",
        },
        headers=headers,
    )
    assert response.status_code == 422


@pytest.mark.integration
async def test_create_provider_and_admin_writes_user_and_audit_log(
    api_client, seeded, db
) -> None:
    """建服务商 + 建管理员 -> 账号 role / provider_id 对，audit_log 有记录。"""
    headers = _platform_headers(seeded)

    created = await api_client.post(
        PROVIDERS_URL,
        json={
            "name": "戊服务商",
            "contact_phone": "13900000008",
            "commission_rate": "0.12",
        },
        headers=headers,
    )
    assert created.status_code == 201
    provider_id = created.json()["id"]

    admin = await api_client.post(
        "{}/{}/admin".format(PROVIDERS_URL, provider_id),
        json={"phone": "13800000008"},
        headers=headers,
    )
    assert admin.status_code == 201
    admin_body = admin.json()
    assert admin_body["phone"] == "13800000008"
    assert admin_body["role"] == "PROVIDER_ADMIN"
    assert admin_body["provider_id"] == provider_id

    maker = async_sessionmaker(db, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        # 账号落在库里，角色与归属都对
        user = (
            await session.execute(select(User).where(User.phone == "13800000008"))
        ).scalar_one()
        assert user.role == UserRole.PROVIDER_ADMIN
        assert user.provider_id == provider_id

        # 建档与建账号都留痕
        logs = (
            (
                await session.execute(
                    select(AuditLog).where(
                        AuditLog.target_type == "service_provider",
                        AuditLog.target_id == provider_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        field_names = sorted(log.field_name for log in logs)
        assert field_names == ["admin_created", "created"]
        for log in logs:
            assert log.operator_type == OperatorType.PLATFORM_ADMIN
            assert log.operator_id == seeded["platform_admin"]
            assert log.provider_id == provider_id


@pytest.mark.integration
async def test_create_provider_admin_rejects_duplicated_phone(api_client, seeded) -> None:
    """手机号已存在 -> 409「手机号已注册」。"""
    headers = _platform_headers(seeded)

    conflict = await api_client.post(
        "{}/{}/admin".format(PROVIDERS_URL, seeded["active"]),
        json={"phone": "13700000001"},  # 平台管理员的手机号
        headers=headers,
    )
    assert conflict.status_code == 409
    assert conflict.json() == {"detail": "手机号已注册"}


@pytest.mark.integration
async def test_create_provider_admin_for_missing_provider_returns_404(
    api_client, seeded
) -> None:
    """服务商不存在 -> 404。"""
    headers = _platform_headers(seeded)
    response = await api_client.post(
        "{}/{}/admin".format(PROVIDERS_URL, seeded["active"] + 100000),
        json={"phone": "13800000009"},
        headers=headers,
    )
    assert response.status_code == 404


@pytest.mark.integration
async def test_create_provider_admin_rejects_provider_id_in_body(
    api_client, seeded
) -> None:
    """请求体里带 provider_id -> 422（归属只由路径决定）。"""
    headers = _platform_headers(seeded)
    response = await api_client.post(
        "{}/{}/admin".format(PROVIDERS_URL, seeded["active"]),
        json={"phone": "13800000009", "provider_id": seeded["pending"]},
        headers=headers,
    )
    assert response.status_code == 422


# =====================================================================
# 列表：分页与过滤
# =====================================================================


@pytest.mark.integration
async def test_list_providers_returns_all_with_pagination(api_client, seeded) -> None:
    """列表带分页信息（page / limit / total）。"""
    headers = _platform_headers(seeded)
    response = await api_client.get(PROVIDERS_URL, headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert body["page"] == 1
    assert body["limit"] == 20
    assert [item["name"] for item in body["items"]] == [
        "待审核服务商",
        "营业中服务商",
        "已冻结服务商",
    ]


@pytest.mark.integration
async def test_list_providers_filters_by_status(api_client, seeded) -> None:
    """按状态过滤。"""
    headers = _platform_headers(seeded)
    response = await api_client.get(
        PROVIDERS_URL, params={"status": "FROZEN"}, headers=headers
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["status"] == "FROZEN"


@pytest.mark.integration
async def test_list_providers_pages(api_client, seeded) -> None:
    """分页：page=2 只剩下一页的条目。"""
    headers = _platform_headers(seeded)
    response = await api_client.get(
        PROVIDERS_URL, params={"page": 2, "limit": 2}, headers=headers
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert body["page"] == 2
    assert body["limit"] == 2
    assert len(body["items"]) == 1


@pytest.mark.integration
async def test_created_provider_shows_up_in_list(api_client, seeded) -> None:
    """新建的服务商出现在列表里（前端刷新后不会看到幽灵数据）。"""
    headers = _platform_headers(seeded)
    await api_client.post(
        PROVIDERS_URL,
        json={
            "name": "己服务商",
            "contact_phone": "13900000007",
            "commission_rate": "0.05",
        },
        headers=headers,
    )
    response = await api_client.get(PROVIDERS_URL, headers=headers)
    assert response.status_code == 200
    names = [item["name"] for item in response.json()["items"]]
    assert "己服务商" in names
