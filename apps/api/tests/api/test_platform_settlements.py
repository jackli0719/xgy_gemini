"""平台侧结算单列表接口的测试（/api/v1/platform/settlements）。

必测点：

1. **鉴权**：PLATFORM_FINANCE 与 PLATFORM_ADMIN 都能进（**看**）；
   普通用户 / 服务商账号 / 平台运营 -> 403，且是**碰库之前**就挡住
   （不泄露任何结算单信息）；没 token -> 401。
2. **分页 + 筛选正确**：page / limit / total 对得上；
   status / provider_id 能筛；两个条件是「与」的关系；limit 上限 100。
3. **不返回内部字段**：确认人 id、创建 / 更新时间戳都不在响应里。
4. **确认仍限财务**（配套的写接口）：PLATFORM_FINANCE -> 200，
   PLATFORM_ADMIN -> 403。看得到列表不等于能确认。

集成测试用的数据库是 TEST_DATABASE_URL 指向的独立测试库
（集成 fixture 每次 drop_all + create_all，绝不碰开发库）。
"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.auth import create_access_token
from app.core.database import get_session
from app.main import app
from app.models.base import Base
from app.models.enums import SettlementStatus, UserRole
from app.models.provider import ServiceProvider
from app.models.settlement import Settlement
from app.models.user import User

SETTLEMENTS_URL = "/api/v1/platform/settlements"

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
    """造平台账号（财务 / 管理员 / 运营 / 普通用户）、服务商账号与两个服务商。

    **不显式指定 id**：让数据库序列自己分配（显式写 id 会让序列停在 1，
    后面服务新建的行拿到 id=1 撞车）。
    """
    maker = async_sessionmaker(db, class_=AsyncSession, expire_on_commit=False)
    period_start = date(2026, 1, 1)
    period_end = date(2026, 1, 31)

    async with maker() as session:
        finance = User(
            phone="13700000001",
            nickname="平台财务",
            role=UserRole.PLATFORM_FINANCE,
            provider_id=None,
        )
        platform_admin = User(
            phone="13700000002",
            nickname="平台管理员",
            role=UserRole.PLATFORM_ADMIN,
            provider_id=None,
        )
        platform_ops = User(
            phone="13700000003",
            nickname="平台运营",
            role=UserRole.PLATFORM_OPS,
            provider_id=None,
        )
        plain_user = User(phone="13700000004", nickname="普通用户")
        session.add_all([finance, platform_admin, platform_ops, plain_user])
        await session.flush()

        provider_a = ServiceProvider(name="甲服务商", contact_phone="13900000001")
        provider_b = ServiceProvider(name="乙服务商", contact_phone="13900000002")
        session.add_all([provider_a, provider_b])
        await session.flush()

        # 服务商账号必须带 provider_id（数据库 CHECK 约束强制）
        provider_admin = User(
            phone="13800000005",
            nickname="服务商管理员",
            role=UserRole.PROVIDER_ADMIN,
            provider_id=provider_a.id,
        )
        session.add(provider_admin)
        await session.flush()

        # 甲服务商两张单：一张待结算、一张已确认
        settlement_a_pending = Settlement(
            provider_id=provider_a.id,
            period_start=period_start,
            period_end=period_end,
            total_amount=Decimal("1000.00"),
            commission_amount=Decimal("100.00"),
            net_amount=Decimal("900.00"),
            status=SettlementStatus.PENDING,
        )
        settlement_a_confirmed = Settlement(
            provider_id=provider_a.id,
            period_start=period_start,
            period_end=date(2026, 2, 28),
            total_amount=Decimal("500.00"),
            commission_amount=Decimal("50.00"),
            net_amount=Decimal("450.00"),
            status=SettlementStatus.CONFIRMED,
            confirmed_by=finance.id,
            confirmed_at=datetime(2026, 3, 1, 8, 0, tzinfo=timezone.utc),
        )
        # 乙服务商一张待结算（跨服务商数据：财务必须看得见）
        settlement_b_pending = Settlement(
            provider_id=provider_b.id,
            period_start=period_start,
            period_end=period_end,
            total_amount=Decimal("200.00"),
            commission_amount=Decimal("20.00"),
            net_amount=Decimal("180.00"),
            status=SettlementStatus.PENDING,
        )
        session.add_all(
            [settlement_a_pending, settlement_a_confirmed, settlement_b_pending]
        )
        await session.flush()
        await session.commit()

        return {
            "finance": finance.id,
            "platform_admin": platform_admin.id,
            "platform_ops": platform_ops.id,
            "plain_user": plain_user.id,
            "provider_admin": provider_admin.id,
            "provider_a": provider_a.id,
            "provider_b": provider_b.id,
            "settlement_a_pending": settlement_a_pending.id,
            "settlement_a_confirmed": settlement_a_confirmed.id,
            "settlement_b_pending": settlement_b_pending.id,
        }


@pytest.fixture
async def seeded(db) -> dict[str, int]:
    return await _seed(db)


def _finance_headers(seeded: dict[str, int]) -> dict[str, str]:
    return _auth_header(seeded["finance"], UserRole.PLATFORM_FINANCE, None)


# =====================================================================
# 鉴权
# =====================================================================


@pytest.mark.integration
async def test_list_settlements_requires_authentication(api_client, seeded) -> None:
    """没有 token -> 401。"""
    response = await api_client.get(SETTLEMENTS_URL)
    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}


@pytest.mark.integration
async def test_list_settlements_rejects_plain_user(api_client, seeded) -> None:
    """普通用户 -> 403。"""
    headers = _auth_header(seeded["plain_user"], UserRole.USER, None)
    response = await api_client.get(SETTLEMENTS_URL, headers=headers)
    assert response.status_code == 403
    assert response.json() == {"detail": "Forbidden"}


@pytest.mark.integration
async def test_list_settlements_rejects_provider_admin(api_client, seeded) -> None:
    """服务商账号 -> 403：平台财务的接口与服务商侧不是一回事。"""
    headers = _auth_header(
        seeded["provider_admin"], UserRole.PROVIDER_ADMIN, seeded["provider_a"]
    )
    response = await api_client.get(SETTLEMENTS_URL, headers=headers)
    assert response.status_code == 403


@pytest.mark.integration
async def test_list_settlements_allows_platform_admin(api_client, seeded) -> None:
    """平台管理员 -> 200：**能看**。

    管理员管全局（服务商入驻、订单总览），对账、核查服务商的结算情况
    是它的日常——所以列表接口也放它。

    注意这里只是「看」：确认结算是另一回事，见本文件末尾的
    确认接口用例（管理员确认 -> 403）。
    """
    headers = _auth_header(seeded["platform_admin"], UserRole.PLATFORM_ADMIN, None)
    response = await api_client.get(SETTLEMENTS_URL, headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert {item["provider_name"] for item in body["items"]} == {
        "甲服务商",
        "乙服务商",
    }


@pytest.mark.integration
async def test_list_settlements_rejects_platform_ops(api_client, seeded) -> None:
    """平台运营 -> 403（运营看得见订单总览，但确认结算是财务的事）。"""
    headers = _auth_header(seeded["platform_ops"], UserRole.PLATFORM_OPS, None)
    response = await api_client.get(SETTLEMENTS_URL, headers=headers)
    assert response.status_code == 403


@pytest.mark.integration
async def test_list_settlements_allows_finance(api_client, seeded) -> None:
    """平台财务 -> 200。"""
    headers = _finance_headers(seeded)
    response = await api_client.get(SETTLEMENTS_URL, headers=headers)
    assert response.status_code == 200
    assert response.json()["total"] == 3


# =====================================================================
# 列表内容
# =====================================================================


@pytest.mark.integration
async def test_list_settlements_returns_all_across_providers(api_client, seeded) -> None:
    """不筛选 -> 全量结算单（含两家服务商的）。

    财务看的是全平台，这是平台侧的特权，来自角色不是来自参数。
    """
    headers = _finance_headers(seeded)
    response = await api_client.get(SETTLEMENTS_URL, headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert {item["provider_name"] for item in body["items"]} == {
        "甲服务商",
        "乙服务商",
    }


@pytest.mark.integration
async def test_list_settlements_item_fields(api_client, seeded) -> None:
    """列表项字段齐：id / 服务商 / 周期 / 金额三件套 / 状态 / 确认时间。

    金额口径：合计 = 佣金 + 实收。
    """
    headers = _finance_headers(seeded)
    response = await api_client.get(SETTLEMENTS_URL, headers=headers)
    assert response.status_code == 200
    by_id = {item["id"]: item for item in response.json()["items"]}

    pending = by_id[seeded["settlement_a_pending"]]
    assert pending["provider_name"] == "甲服务商"
    assert pending["period_start"] == "2026-01-01"
    assert pending["period_end"] == "2026-01-31"
    assert pending["total_amount"] == "1000.00"
    assert pending["commission_amount"] == "100.00"
    assert pending["net_amount"] == "900.00"
    assert pending["status"] == "PENDING"
    assert pending["confirmed_at"] is None

    confirmed = by_id[seeded["settlement_a_confirmed"]]
    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["confirmed_at"] is not None
    assert confirmed["confirmed_at"].startswith("2026-03-01T08:00:00")


@pytest.mark.integration
async def test_list_settlements_does_not_return_internal_fields(api_client, seeded) -> None:
    """不返回内部字段：确认人 id、创建 / 更新时间戳都不在响应里。"""
    headers = _finance_headers(seeded)
    response = await api_client.get(SETTLEMENTS_URL, headers=headers)
    assert response.status_code == 200
    for item in response.json()["items"]:
        assert set(item) == {
            "id",
            "provider_name",
            "period_start",
            "period_end",
            "total_amount",
            "commission_amount",
            "net_amount",
            "status",
            "confirmed_at",
        }


@pytest.mark.integration
async def test_list_settlements_includes_provider_filter_options(api_client, seeded) -> None:
    """筛选栏的服务商选项：有过结算单的服务商都在（按 id 排序）。

    平台侧的服务商列表接口只对平台管理员开放，而财务调不了那个接口，
    所以结算单接口自己带上筛选选项。
    """
    headers = _finance_headers(seeded)
    response = await api_client.get(SETTLEMENTS_URL, headers=headers)
    assert response.status_code == 200
    providers = response.json()["providers"]
    assert providers == [
        {"id": seeded["provider_a"], "name": "甲服务商"},
        {"id": seeded["provider_b"], "name": "乙服务商"},
    ]


# =====================================================================
# 筛选
# =====================================================================


@pytest.mark.integration
async def test_list_settlements_filters_by_status(api_client, seeded) -> None:
    """按状态筛选。"""
    headers = _finance_headers(seeded)
    response = await api_client.get(
        SETTLEMENTS_URL, params={"status": "PENDING"}, headers=headers
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert {item["status"] for item in body["items"]} == {"PENDING"}


@pytest.mark.integration
async def test_list_settlements_filters_by_provider(api_client, seeded) -> None:
    """按 provider_id 筛选：只出这一家的单。"""
    headers = _finance_headers(seeded)
    response = await api_client.get(
        SETTLEMENTS_URL,
        params={"provider_id": seeded["provider_a"]},
        headers=headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert {item["provider_name"] for item in body["items"]} == {"甲服务商"}


@pytest.mark.integration
async def test_list_settlements_filters_combine(api_client, seeded) -> None:
    """状态 + 服务商一起筛：条件是「与」的关系。"""
    headers = _finance_headers(seeded)
    response = await api_client.get(
        SETTLEMENTS_URL,
        params={"status": "PENDING", "provider_id": seeded["provider_a"]},
        headers=headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == seeded["settlement_a_pending"]


@pytest.mark.integration
async def test_list_settlements_rejects_unknown_status(api_client, seeded) -> None:
    """状态取值不在枚举里 -> 422（接口层挡住，不进 service）。"""
    headers = _finance_headers(seeded)
    response = await api_client.get(
        SETTLEMENTS_URL, params={"status": "NOT_A_STATUS"}, headers=headers
    )
    assert response.status_code == 422


# =====================================================================
# 分页
# =====================================================================


@pytest.mark.integration
async def test_list_settlements_pages(api_client, seeded) -> None:
    """分页：page=2 只剩下一页的条目，total 不受分页影响。"""
    headers = _finance_headers(seeded)
    response = await api_client.get(
        SETTLEMENTS_URL, params={"page": 2, "limit": 2}, headers=headers
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert body["page"] == 2
    assert body["limit"] == 2
    assert len(body["items"]) == 1


@pytest.mark.integration
async def test_list_settlements_clamps_limit_to_100(api_client, seeded) -> None:
    """分页上限 100：传 500 时按 100 算（不报错），回显收敛后的值。"""
    headers = _finance_headers(seeded)
    response = await api_client.get(
        SETTLEMENTS_URL, params={"limit": 500}, headers=headers
    )
    assert response.status_code == 200
    assert response.json()["limit"] == 100


@pytest.mark.integration
async def test_list_settlements_limit_cap_also_bounds_returned_rows(
    api_client, db, seeded
) -> None:
    """上限不只是回显：**实际取回的行数**也不超过 100。

    这一条钉住「回显的 limit」与「真的取了这么多行」是同一件事——
    只回显不收敛的话，页面会按 100 条一页翻页，实际每页却来 500 条。
    """
    maker = async_sessionmaker(db, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        base = date(2026, 3, 1)
        for i in range(120):
            session.add(
                Settlement(
                    provider_id=seeded["provider_a"],
                    # 周期各不相同：同一服务商的同一周期只能有一张单
                    period_start=base + timedelta(days=i),
                    period_end=base + timedelta(days=i),
                    total_amount=Decimal("10.00"),
                    commission_amount=Decimal("1.00"),
                    net_amount=Decimal("9.00"),
                    status=SettlementStatus.PENDING,
                )
            )
        await session.commit()

    headers = _finance_headers(seeded)
    response = await api_client.get(
        SETTLEMENTS_URL, params={"limit": 500}, headers=headers
    )
    assert response.status_code == 200
    body = response.json()
    assert body["limit"] == 100
    assert body["total"] == 123
    assert len(body["items"]) == 100


@pytest.mark.integration
async def test_list_settlements_rejects_zero_limit(api_client, seeded) -> None:
    """limit 必须 >= 1 -> 422（接口层就挡住，不进 service）。"""
    headers = _finance_headers(seeded)
    response = await api_client.get(
        SETTLEMENTS_URL, params={"limit": 0}, headers=headers
    )
    assert response.status_code == 422


@pytest.mark.integration
async def test_list_settlements_rejects_non_positive_provider_id(api_client, seeded) -> None:
    """provider_id 必须 > 0 -> 422。"""
    headers = _finance_headers(seeded)
    response = await api_client.get(
        SETTLEMENTS_URL, params={"provider_id": 0}, headers=headers
    )
    assert response.status_code == 422


# =====================================================================
# 配套的「确认」接口：看得到 ≠ 确认得了
# =====================================================================


def _confirm_url(settlement_id: int) -> str:
    return "/api/v1/settlements/{}/confirm".format(settlement_id)


async def _settlement_of(db, settlement_id: int) -> Settlement:
    maker = async_sessionmaker(db, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        return (
            await session.execute(
                select(Settlement).where(Settlement.id == settlement_id)
            )
        ).scalar_one()


@pytest.mark.integration
async def test_confirm_settlement_allows_finance(api_client, db, seeded) -> None:
    """平台财务 -> 200：确认得了。"""
    headers = _finance_headers(seeded)
    response = await api_client.post(
        _confirm_url(seeded["settlement_a_pending"]), headers=headers
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "CONFIRMED"

    settlement = await _settlement_of(db, seeded["settlement_a_pending"])
    assert settlement.status == SettlementStatus.CONFIRMED


@pytest.mark.integration
async def test_confirm_settlement_rejects_platform_admin(api_client, db, seeded) -> None:
    """平台管理员 -> 403：**看得见列表，但确认不了**。

    确认结算是把钱定下来的动作，只归财务。管理员看得见列表是为了对账，
    不是为了替财务点确认。
    """
    headers = _auth_header(seeded["platform_admin"], UserRole.PLATFORM_ADMIN, None)
    response = await api_client.post(
        _confirm_url(seeded["settlement_a_pending"]), headers=headers
    )
    assert response.status_code == 403

    # 数据一点没动
    settlement = await _settlement_of(db, seeded["settlement_a_pending"])
    assert settlement.status == SettlementStatus.PENDING
    assert settlement.confirmed_by is None
    assert settlement.confirmed_at is None


@pytest.mark.integration
async def test_confirm_settlement_rejects_other_roles(api_client, db, seeded) -> None:
    """其他角色（运营 / 普通用户 / 服务商账号）-> 403。"""
    cases = [
        _auth_header(seeded["platform_ops"], UserRole.PLATFORM_OPS, None),
        _auth_header(seeded["plain_user"], UserRole.USER, None),
        _auth_header(
            seeded["provider_admin"], UserRole.PROVIDER_ADMIN, seeded["provider_a"]
        ),
    ]
    for headers in cases:
        response = await api_client.post(
            _confirm_url(seeded["settlement_a_pending"]), headers=headers
        )
        assert response.status_code == 403

    settlement = await _settlement_of(db, seeded["settlement_a_pending"])
    assert settlement.status == SettlementStatus.PENDING
