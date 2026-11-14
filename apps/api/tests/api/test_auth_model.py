"""鉴权模型（角色 + 服务商归属）的测试。

覆盖三层：

- **纯函数镜像**：数据库 CHECK 约束 ck_user_role_provider 的 Python 版本
  （app.core.auth.is_valid_role_provider_pair）与约束原文一致；
- **数据库真约束**：真的往 PostgreSQL 里插违规数据，看数据库是不是真的拒绝；
- **令牌与作用域**：JWT 往返、require_provider_scope 的放行/拒绝，
  以及 403 消息在各种失败场景下逐字一致。

集成测试用的数据库是 TEST_DATABASE_URL 指向的独立测试库
（集成 fixture 每次 drop_all + create_all，绝不碰开发库）。
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import httpx
import jwt
import pytest
from fastapi import APIRouter, Depends, FastAPI
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.auth import (
    FORBIDDEN_DETAIL,
    CurrentUser,
    create_access_token,
    is_valid_role_provider_pair,
    require_provider_scope,
)
from app.core.config import settings
from app.models.base import Base
from app.models.enums import UserRole
from app.models.provider import ServiceProvider
from app.models.user import USER_ROLE_PROVIDER_CHECK_SQL, User

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

# 迁移文件路径：用来比对「模型里的约束文本」与「迁移里的约束文本」是否逐字一致
_MIGRATION_PATH = (
    Path(__file__).resolve().parents[2] / "alembic" / "versions" / "0004_user_role_provider.py"
)


def _load_migration_module():
    """按路径加载迁移模块（alembic/versions 不是包）。

    只读取模块里的常量，不调用 upgrade / downgrade——
    这里要的是「迁移文件里写的那段 SQL」，不是执行结果。
    """
    spec = importlib.util.spec_from_file_location(
        "migration_0004_user_role_provider", _MIGRATION_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

# 用户角色取值（与 app.models.enums.UserRole 一致，测试里独立写一遍，
# 免得「枚举改了但数据库没改」这种偏差被同一个常量掩盖掉）
EXPECTED_ROLE_VALUES = (
    "USER",
    "MASTER",
    "PROVIDER_ADMIN",
    "PROVIDER_STAFF",
    "PLATFORM_ADMIN",
    "PLATFORM_OPS",
    "PLATFORM_FINANCE",
    "PLATFORM_CS",
)


# =====================================================================
# 单元测试：CHECK 约束的纯函数镜像
# =====================================================================


@pytest.mark.parametrize(
    "role, provider_id, expected",
    [
        # 服务商侧角色必须带 provider_id
        (UserRole.PROVIDER_ADMIN, None, False),
        (UserRole.PROVIDER_ADMIN, 100, True),
        (UserRole.PROVIDER_STAFF, None, False),
        (UserRole.PROVIDER_STAFF, 100, True),
        # 其余角色必须不带 provider_id
        (UserRole.USER, None, True),
        (UserRole.USER, 100, False),
        (UserRole.MASTER, None, True),
        (UserRole.MASTER, 100, False),
        (UserRole.PLATFORM_ADMIN, None, True),
        (UserRole.PLATFORM_ADMIN, 100, False),
    ],
)
def test_role_provider_pair_validity(role, provider_id, expected) -> None:
    """纯函数镜像的判定结果。

    这组取值必须与数据库 CHECK 约束 ck_user_role_provider 完全一致——
    不一致就意味着「代码认为合法、数据库拒绝」或者反过来，
    两种都足以让派单链路踩坑。
    """
    assert is_valid_role_provider_pair(role, provider_id) is expected


def test_user_role_enum_values_are_exactly_the_expected_ones() -> None:
    """UserRole 的取值集合就是卡片约定的八个。"""
    assert tuple(r.value for r in UserRole) == EXPECTED_ROLE_VALUES


def test_check_constraint_text_matches_the_migration() -> None:
    """模型里的 CHECK 约束文本与迁移 0004 里的原文逐字一致。

    模型是测试库建表的依据（create_all），迁移是生产库建表的依据。
    两边文本只要有一个字不同，就会长出两套规则——
    而 alembic check 并不比对 CHECK 约束，所以这条测试是唯一的哨兵。
    """
    migration = _load_migration_module()
    assert USER_ROLE_PROVIDER_CHECK_SQL == migration.ROLE_PROVIDER_CHECK_SQL


def test_migration_revision_chain_is_continuous() -> None:
    """迁移挂在 0003 之后（revision / down_revision 不能写错）。"""
    migration = _load_migration_module()
    assert migration.revision == "0004_user_role_provider"
    assert migration.down_revision == "0003_order_slot_id"


def test_migration_user_role_values_match_the_enum() -> None:
    """迁移里建的枚举取值与 UserRole 一致（值集合与顺序都一致）。"""
    migration = _load_migration_module()
    assert tuple(migration.USER_ROLE) == EXPECTED_ROLE_VALUES


# =====================================================================
# 单元测试：require_provider_scope（不需要数据库——它刻意不查库）
# =====================================================================

_probe_app = FastAPI()
_probe_router = APIRouter()


@_probe_router.get("/probe")
async def _probe(current: CurrentUser = Depends(require_provider_scope)):
    """探针接口：只有通过 require_provider_scope 才能进来。"""
    return {
        "user_id": current.user_id,
        "role": current.role.value,
        "provider_id": current.provider_id,
    }


_probe_app.include_router(_probe_router)


@pytest.fixture
async def probe_client():
    """直连 ASGI 的 HTTP 客户端（不起服务、不碰数据库）。"""
    transport = httpx.ASGITransport(app=_probe_app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


def _token_header(user_id: int, role: UserRole, provider_id: int | None) -> dict[str, str]:
    return {"Authorization": "Bearer {}".format(create_access_token(user_id, role, provider_id))}


def create_provider_admin_token(provider_id: int, *, user_id: int = 1) -> str:
    """服务商管理员的访问令牌。"""
    return create_access_token(user_id, UserRole.PROVIDER_ADMIN, provider_id)


def create_master_token(*, user_id: int = 1) -> str:
    """师傅的访问令牌。

    师傅的服务商归属权威来源是 master 表，token 里不带 provider_id
    （user.provider_id 对师傅角色必须为空）。
    """
    return create_access_token(user_id, UserRole.MASTER, None)


async def test_require_provider_scope_allows_provider_admin(probe_client) -> None:
    """服务商管理员 + 有归属 -> 放行。"""
    token = create_provider_admin_token(100)
    response = await probe_client.get(
        "/probe", headers={"Authorization": "Bearer {}".format(token)}
    )
    assert response.status_code == 200
    assert response.json() == {
        "user_id": 1,
        "role": "PROVIDER_ADMIN",
        "provider_id": 100,
    }


async def test_require_provider_scope_rejects_master_token(probe_client) -> None:
    """师傅账号进不了服务商作用域。

    师傅的服务商归属在 master 表里，token 上没有 provider_id，
    所以它不能借用「服务商作用域」这个入口去碰订单。
    """
    response = await probe_client.get(
        "/probe", headers={"Authorization": "Bearer {}".format(create_master_token())}
    )
    assert response.status_code == 403
    assert response.json() == {"detail": FORBIDDEN_DETAIL}


async def test_require_provider_scope_allows_provider_staff(probe_client) -> None:
    """服务商员工 + 有归属 -> 放行。"""
    response = await probe_client.get("/probe", headers=_token_header(1, UserRole.PROVIDER_STAFF, 100))
    assert response.status_code == 200
    assert response.json()["role"] == "PROVIDER_STAFF"
    assert response.json()["provider_id"] == 100


@pytest.mark.parametrize(
    "role, provider_id",
    [
        (UserRole.USER, None),
        (UserRole.MASTER, None),
        (UserRole.PLATFORM_ADMIN, None),
        # 角色对但没有归属：数据库 CHECK 保证不了这种数据存在，
        # 但令牌可能被伪造或签发逻辑出错，作用域依赖必须自己挡住
        (UserRole.PROVIDER_ADMIN, None),
    ],
)
async def test_require_provider_scope_rejects(probe_client, role, provider_id) -> None:
    """不在服务商作用域内 -> 403。"""
    response = await probe_client.get("/probe", headers=_token_header(1, role, provider_id))
    assert response.status_code == 403
    assert response.json() == {"detail": FORBIDDEN_DETAIL}


async def test_forbidden_message_is_identical_across_failure_reasons(probe_client) -> None:
    """403 消息不区分失败原因：两种失败场景的消息逐字相同。

    「角色不对」和「provider_id 缺失」如果给不同消息，
    攻击者就能靠报错差异反推某个账号的服务商归属。
    """
    wrong_role = await probe_client.get("/probe", headers=_token_header(1, UserRole.USER, None))
    missing_provider = await probe_client.get(
        "/probe", headers=_token_header(1, UserRole.PROVIDER_ADMIN, None)
    )
    assert wrong_role.status_code == 403
    assert missing_provider.status_code == 403
    # 逐字相同（不是「差不多」，是同一个字节序列）
    assert wrong_role.json()["detail"] == missing_provider.json()["detail"]
    assert wrong_role.json()["detail"] == FORBIDDEN_DETAIL


async def test_old_token_without_role_is_rejected(probe_client) -> None:
    """旧版 token（没有 role claim）-> 401，不做兼容。

    「缺 role 就当普通用户」等于给旧 token 开后门：
    旧 token 是签发逻辑改动之前流出去的，无法保证归属正确。
    """
    payload = {
        "sub": "1",
        "iat": 0,
        "exp": 4102444800,
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_alg)
    response = await probe_client.get(
        "/probe", headers={"Authorization": "Bearer {}".format(token)}
    )
    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}


# =====================================================================
# 集成测试：真实 PostgreSQL
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


def _maker(db) -> async_sessionmaker:
    return async_sessionmaker(db, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
async def provider_id(db) -> int:
    """先建一个服务商。

    必须先有合法的 service_provider 行，插用户时的外键才是通的——
    否则「插 USER 带 provider_id」被拒可能是外键拒绝的，不一定是 CHECK 拒绝的，
    测试就变成在验证错误的原因。
    """
    maker = _maker(db)
    async with maker() as session:
        provider = ServiceProvider(id=1, name="测试服务商", contact_phone="13800000001")
        session.add(provider)
        await session.commit()
        return provider.id


async def _insert_user(db, *, phone: str, role: UserRole, provider_id: int | None) -> None:
    """插一行用户并提交；触发约束时抛 IntegrityError。"""
    maker = _maker(db)
    async with maker() as session:
        session.add(User(id=1, phone=phone, role=role, provider_id=provider_id))
        await session.commit()


@pytest.mark.integration
async def test_check_constraint_rejects_provider_admin_without_provider(
    db, provider_id
) -> None:
    """服务商角色却不带 provider_id -> 数据库拒绝。"""
    with pytest.raises(IntegrityError):
        await _insert_user(
            db,
            phone="13800000001",
            role=UserRole.PROVIDER_ADMIN,
            provider_id=None,
        )


@pytest.mark.integration
async def test_check_constraint_rejects_user_with_provider(db, provider_id) -> None:
    """普通用户却带 provider_id -> 数据库拒绝。

    provider_id 指向的是真实存在的服务商，所以拒它的只能是 CHECK 约束。
    """
    with pytest.raises(IntegrityError):
        await _insert_user(
            db,
            phone="13800000002",
            role=UserRole.USER,
            provider_id=provider_id,
        )


@pytest.mark.integration
async def test_check_constraint_rejects_master_with_provider(db, provider_id) -> None:
    """师傅账号带 provider_id -> 数据库拒绝。

    师傅的服务商归属权威来源是 master 表，不是 user.provider_id。
    """
    with pytest.raises(IntegrityError):
        await _insert_user(
            db,
            phone="13800000003",
            role=UserRole.MASTER,
            provider_id=provider_id,
        )


@pytest.mark.integration
async def test_check_constraint_accepts_provider_admin_with_provider(
    db, provider_id
) -> None:
    """服务商管理员带 provider_id -> 允许，且数据原样落库。"""
    await _insert_user(
        db,
        phone="13800000004",
        role=UserRole.PROVIDER_ADMIN,
        provider_id=provider_id,
    )
    maker = _maker(db)
    async with maker() as session:
        user = (await session.execute(select(User))).scalar_one()
        assert user.role == UserRole.PROVIDER_ADMIN
        assert user.provider_id == provider_id


@pytest.mark.integration
async def test_default_role_for_plain_user_is_user(db, provider_id) -> None:
    """不显式给 role 的账号，落到默认角色 USER 且没有服务商归属。"""
    maker = _maker(db)
    async with maker() as session:
        session.add(User(id=1, phone="13800000005"))
        await session.commit()
    async with maker() as session:
        user = (await session.execute(select(User))).scalar_one()
        assert user.role == UserRole.USER
        assert user.provider_id is None


@pytest.mark.integration
async def test_check_constraint_exists_in_database(db, provider_id) -> None:
    """库里确实有 ck_user_role_provider 这条约束（不是只在 Python 里说说）。"""
    maker = _maker(db)
    async with maker() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conrelid = '\"user\"'::regclass AND contype = 'c'"
                )
            )
        ).all()
    names = {row[0] for row in rows}
    assert "ck_user_role_provider" in names


@pytest.mark.integration
async def test_user_role_enum_values_in_database(db, provider_id) -> None:
    """库里的 user_role 枚举取值就是约定的八个。"""
    maker = _maker(db)
    async with maker() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT enumlabel FROM pg_enum "
                    "JOIN pg_type ON pg_type.oid = pg_enum.enumtypid "
                    "WHERE pg_type.typname = 'user_role' ORDER BY enumsortorder"
                )
            )
        ).all()
    assert tuple(row[0] for row in rows) == EXPECTED_ROLE_VALUES


@pytest.mark.integration
async def test_jwt_round_trip_carries_role_and_provider(probe_client, provider_id) -> None:
    """签发的令牌能原样带回 role 和 provider_id。"""
    token = create_provider_admin_token(provider_id)
    payload = jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[settings.jwt_alg],
        options={"require": ["exp", "sub", "role"]},
    )
    assert payload["role"] == "PROVIDER_ADMIN"
    assert payload["provider_id"] == provider_id

    # 走真实的鉴权依赖再解一遍，确认 get_current_user 解出来的也是同一组值
    response = await probe_client.get(
        "/probe", headers={"Authorization": "Bearer {}".format(token)}
    )
    assert response.status_code == 200
    assert response.json() == {
        "user_id": 1,
        "role": "PROVIDER_ADMIN",
        "provider_id": provider_id,
    }
