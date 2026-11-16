"""服务商侧师傅管理接口的测试（PATCH /provider/masters/{master_id}）。

必测点：

1. **改别商师傅 -> 404，且与「不存在」同构**（R1）：
   响应里只有一个 master_id，归属信息一个字都没有；
2. **改本商师傅 -> 成功，且 audit_log 有记录**：
   留痕（R3）——谁、把谁、从什么状态改成了什么状态，都查得到；
3. **鉴权**：没 token -> 401；不是服务商侧角色 -> 403；
4. **请求体只认 status**：PENDING 不许设置（422），带 provider_id 也 422。

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
from app.models.enums import MasterStatus, OperatorType, UserRole
from app.models.provider import Master, ServiceProvider
from app.models.user import User

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
    """造两个服务商、各自的管理员 / 员工 / 师傅。

    **不显式指定 id**：让数据库序列自己分配。显式写 id 会让序列停在 1，
    后面服务新建的行拿到 id=1，跟已存在的行撞车。id 一律从落库对象上取。
    """
    maker = async_sessionmaker(db, class_=AsyncSession, expire_on_commit=False)

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
        staff_a = User(
            phone="13800000002",
            nickname="甲员工",
            role=UserRole.PROVIDER_STAFF,
            provider_id=provider_a.id,
        )
        admin_b = User(
            phone="13800000003",
            nickname="乙管理员",
            role=UserRole.PROVIDER_ADMIN,
            provider_id=provider_b.id,
        )
        plain_user = User(phone="13800000004", nickname="普通用户")
        # 每个师傅一个独立账号：master.user_id 上有唯一约束
        # （uq_master_user_id），一个登录用户最多对应一个师傅身份
        master_user_a1 = User(phone="13800000005", nickname="师傅甲一账号")
        master_user_a2 = User(phone="13800000006", nickname="师傅甲二账号")
        master_user_b1 = User(phone="13800000007", nickname="师傅乙一账号")
        session.add_all(
            [
                admin_a,
                staff_a,
                admin_b,
                plain_user,
                master_user_a1,
                master_user_a2,
                master_user_b1,
            ]
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
        # 乙服务商还有一个**待审核**的师傅：入驻登记之后 PENDING 的师傅
        # 是全平台存在的（申请人自选服务商），所以「别家待审核的师傅」
        # 必须与「别家已入职的师傅」响应同构（见下面的 404 同构用例）
        master_user_b2 = User(
            phone="13800000008",
            nickname="师傅乙二账号",
            role=UserRole.MASTER,
        )
        session.add(master_user_b2)
        await session.flush()
        master_b2 = Master(
            provider_id=provider_b.id,
            user_id=master_user_b2.id,
            real_name="师傅乙二",
            status=MasterStatus.PENDING,
            rating=None,
        )
        session.add_all([master_a1, master_a2, master_b1, master_b2])
        await session.flush()
        await session.commit()

        return {
            "provider_a": provider_a.id,
            "provider_b": provider_b.id,
            "admin_a": admin_a.id,
            "staff_a": staff_a.id,
            "admin_b": admin_b.id,
            "plain_user": plain_user.id,
            "master_a1": master_a1.id,
            "master_a2": master_a2.id,
            "master_b1": master_b1.id,
            "master_b2": master_b2.id,
        }


@pytest.fixture
async def seeded(db) -> dict[str, int]:
    return await _seed(db)


def _admin_a_headers(seeded: dict[str, int]) -> dict[str, str]:
    return _auth_header(seeded["admin_a"], UserRole.PROVIDER_ADMIN, seeded["provider_a"])


# =====================================================================
# 归属：别家的师傅改不动
# =====================================================================


@pytest.mark.integration
async def test_patch_foreign_master_status_is_404_and_looks_missing(
    api_client, seeded
) -> None:
    """改别家的师傅 -> 404，且与「这个师傅不存在」的响应逐字同构。

    不泄露存在性：别家的师傅和不存在的师傅在响应里长得一模一样，
    客户端没法靠报错差异判断某个师傅 id 存不存在（R1）。
    """
    headers = _admin_a_headers(seeded)

    response = await api_client.patch(
        "{}/{}".format(MASTERS_URL, seeded["master_b1"]),
        json={"status": "DISABLED"},
        headers=headers,
    )
    assert response.status_code == 404

    missing = await api_client.patch(
        "{}/{}".format(MASTERS_URL, seeded["master_b1"] + 100000),
        json={"status": "DISABLED"},
        headers=headers,
    )
    assert missing.status_code == 404

    # 两句只有客户端自己给的 master_id 不同，归属信息一个字都没有
    assert response.json()["detail"] == "师傅不存在：master_id={}".format(
        seeded["master_b1"]
    )
    assert missing.json()["detail"] == "师傅不存在：master_id={}".format(
        seeded["master_b1"] + 100000
    )


@pytest.mark.integration
async def test_patch_foreign_master_status_does_not_change_anything(
    api_client, seeded, db
) -> None:
    """改别家的师傅 -> 404，而且那一行的状态一个字节都没变。"""
    headers = _admin_a_headers(seeded)
    response = await api_client.patch(
        "{}/{}".format(MASTERS_URL, seeded["master_b1"]),
        json={"status": "DISABLED"},
        headers=headers,
    )
    assert response.status_code == 404

    maker = async_sessionmaker(db, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        master = (
            await session.execute(
                select(Master).where(Master.id == seeded["master_b1"])
            )
        ).scalar_one()
        assert master.status == MasterStatus.ACTIVE


# =====================================================================
# 改本商师傅：成功 + 留痕
# =====================================================================


@pytest.mark.integration
async def test_patch_own_master_status_succeeds(api_client, seeded) -> None:
    """改本商师傅 -> 200，返回改完之后的师傅。"""
    headers = _admin_a_headers(seeded)
    response = await api_client.patch(
        "{}/{}".format(MASTERS_URL, seeded["master_a1"]),
        json={"status": "DISABLED"},
        headers=headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == seeded["master_a1"]
    assert body["real_name"] == "师傅甲一"
    assert body["phone"] == "13800000005"
    assert body["status"] == "DISABLED"


@pytest.mark.integration
async def test_patch_own_master_status_writes_audit_log(api_client, seeded, db) -> None:
    """改本商师傅 -> audit_log 留痕：谁改的、把谁、从什么改成什么。

    留痕是 R3 的要求：师傅状态是「谁能被派单」的开关，改了必须查得到。
    """
    headers = _admin_a_headers(seeded)
    response = await api_client.patch(
        "{}/{}".format(MASTERS_URL, seeded["master_a1"]),
        json={"status": "DISABLED"},
        headers=headers,
    )
    assert response.status_code == 200

    maker = async_sessionmaker(db, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        # 库里的状态确实改了
        master = (
            await session.execute(
                select(Master).where(Master.id == seeded["master_a1"])
            )
        ).scalar_one()
        assert master.status == MasterStatus.DISABLED

        logs = (
            (
                await session.execute(
                    select(AuditLog).where(
                        AuditLog.target_type == "master",
                        AuditLog.target_id == seeded["master_a1"],
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(logs) == 1
        log = logs[0]
        assert log.field_name == "status"
        assert log.old_value == "ACTIVE"
        assert log.new_value == "DISABLED"
        assert log.operator_type == OperatorType.PROVIDER_ADMIN
        assert log.operator_id == seeded["admin_a"]
        assert log.provider_id == seeded["provider_a"]


@pytest.mark.integration
async def test_patch_pending_master_status_is_409(api_client, seeded, db) -> None:
    """待审核（PENDING）的师傅，服务商改不动他的状态 -> 409。

    PENDING 是入驻流程的初始状态，只能由平台审核流转
    （见 app.services.master_onboarding.review_onboarding）。
    服务商提前把待审核的师傅置成 ACTIVE，等于绕过平台审核那道闸门——
    派单那头会真的把单派给他。
    """
    headers = _admin_a_headers(seeded)
    response = await api_client.patch(
        "{}/{}".format(MASTERS_URL, seeded["master_a2"]),
        json={"status": "ACTIVE"},
        headers=headers,
    )
    assert response.status_code == 409

    maker = async_sessionmaker(db, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        master = (
            await session.execute(
                select(Master).where(Master.id == seeded["master_a2"])
            )
        ).scalar_one()
        logs = (
            (
                await session.execute(
                    select(AuditLog).where(
                        AuditLog.target_type == "master",
                        AuditLog.target_id == seeded["master_a2"],
                    )
                )
            )
            .scalars()
            .all()
        )

    # 状态没变，也没有留下任何「改过」的痕迹
    assert master.status == MasterStatus.PENDING
    assert logs == []


@pytest.mark.integration
async def test_patch_foreign_pending_master_is_404_same_as_missing(
    api_client, seeded
) -> None:
    """别家的**待审核**师傅 -> 404，且与「不存在」逐字同构（R1）。

    入驻登记之后，PENDING 的师傅是全平台存在的（申请人自选服务商），
    所以「别家待审核的师傅」与「别家已入职的师傅」必须长得一样——
    否则服务商就能靠报错差异判断别家有没有人在申请入驻。
    """
    headers = _admin_a_headers(seeded)

    response = await api_client.patch(
        "{}/{}".format(MASTERS_URL, seeded["master_b2"]),
        json={"status": "ACTIVE"},
        headers=headers,
    )
    missing = await api_client.patch(
        "{}/999999".format(MASTERS_URL),
        json={"status": "ACTIVE"},
        headers=headers,
    )

    assert response.status_code == 404
    assert missing.status_code == 404
    # 两句只有客户端自己给的 master_id 不同，归属信息一个字都没有
    assert response.json()["detail"] == "师傅不存在：master_id={}".format(
        seeded["master_b2"]
    )
    assert missing.json()["detail"] == "师傅不存在：master_id=999999"


@pytest.mark.integration
async def test_patch_status_records_the_real_operator_role(api_client, seeded, db) -> None:
    """员工改的记 PROVIDER_STAFF，不是 PROVIDER_ADMIN。

    审计日志记**真实操作人**：写死成 PROVIDER_ADMIN 等于把员工的操作
    记在管理员头上，追溯时指错人。
    """
    headers = _auth_header(
        seeded["staff_a"], UserRole.PROVIDER_STAFF, seeded["provider_a"]
    )
    response = await api_client.patch(
        "{}/{}".format(MASTERS_URL, seeded["master_a1"]),
        json={"status": "ON_LEAVE"},
        headers=headers,
    )
    assert response.status_code == 200

    maker = async_sessionmaker(db, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        log = (
            (
                await session.execute(
                    select(AuditLog).where(
                        AuditLog.target_type == "master",
                        AuditLog.target_id == seeded["master_a1"],
                    )
                )
            )
            .scalars()
            .one()
        )
        assert log.operator_type == OperatorType.PROVIDER_STAFF
        assert log.operator_id == seeded["staff_a"]
        assert log.old_value == "ACTIVE"
        assert log.new_value == "ON_LEAVE"


@pytest.mark.integration
async def test_patched_status_shows_up_in_master_list(api_client, seeded) -> None:
    """改完状态，列表里看到的是新状态（前端刷新后不会看到幽灵数据）。"""
    headers = _admin_a_headers(seeded)
    await api_client.patch(
        "{}/{}".format(MASTERS_URL, seeded["master_a1"]),
        json={"status": "DISABLED"},
        headers=headers,
    )
    response = await api_client.get(MASTERS_URL, headers=headers)
    assert response.status_code == 200
    items = {row["id"]: row for row in response.json()["items"]}
    assert items[seeded["master_a1"]]["status"] == "DISABLED"


# =====================================================================
# 列表字段
# =====================================================================


@pytest.mark.integration
async def test_master_list_carries_phone(api_client, seeded) -> None:
    """师傅列表带手机号（后台要靠它联系师傅）。"""
    response = await api_client.get(MASTERS_URL, headers=_admin_a_headers(seeded))
    assert response.status_code == 200
    items = {row["id"]: row for row in response.json()["items"]}
    assert items[seeded["master_a1"]]["phone"] == "13800000005"
    assert items[seeded["master_a2"]]["phone"] == "13800000006"
    # 别家师傅不出现
    assert seeded["master_b1"] not in items


# =====================================================================
# 入参边界
# =====================================================================


@pytest.mark.integration
async def test_patch_master_status_rejects_pending_status(api_client, seeded) -> None:
    """PENDING 不许设置：它是入驻流程的初始状态，422。"""
    headers = _admin_a_headers(seeded)
    response = await api_client.patch(
        "{}/{}".format(MASTERS_URL, seeded["master_a1"]),
        json={"status": "PENDING"},
        headers=headers,
    )
    assert response.status_code == 422


@pytest.mark.integration
async def test_patch_master_status_rejects_provider_id_in_body(
    api_client, seeded
) -> None:
    """请求体里带 provider_id -> 422（而不是被静默忽略）。

    静默忽略会让人以为字段生效了；直接 422 才能把「归属只从 token 来」
    这条边界说清楚。
    """
    headers = _admin_a_headers(seeded)
    response = await api_client.patch(
        "{}/{}".format(MASTERS_URL, seeded["master_a1"]),
        json={"status": "DISABLED", "provider_id": seeded["provider_b"]},
        headers=headers,
    )
    assert response.status_code == 422


# =====================================================================
# 鉴权
# =====================================================================


@pytest.mark.integration
async def test_patch_master_status_requires_authentication(api_client, seeded) -> None:
    """没有 token -> 401。"""
    response = await api_client.patch(
        "{}/{}".format(MASTERS_URL, seeded["master_a1"]),
        json={"status": "DISABLED"},
    )
    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}


@pytest.mark.integration
async def test_patch_master_status_rejects_non_provider_role(api_client, seeded) -> None:
    """普通用户 -> 403（文案与别处的越权失败一致）。"""
    headers = _auth_header(seeded["plain_user"], UserRole.USER, None)
    response = await api_client.patch(
        "{}/{}".format(MASTERS_URL, seeded["master_a1"]),
        json={"status": "DISABLED"},
        headers=headers,
    )
    assert response.status_code == 403
    assert response.json() == {"detail": "Forbidden"}
