"""财务确认结算（T-11b）的 service / 接口测试。

分两类：

- **单元测试**（不碰数据库）：service 的签名边界（确认人只能从
  CurrentUser 来）、异常到 HTTP 状态码的映射、状态机是否被调用；
- **集成测试**（需要真实 PostgreSQL）：真的走 HTTP -> service -> 数据库，
  验证确认 PENDING 结算单、角色不对被挡在库外、已确认 / 不存在同构 404、
  并发确认只成功一次。

集成测试用的数据库是 TEST_DATABASE_URL 指向的独立测试库
（集成 fixture 每次 drop_all + create_all，绝不碰开发库）。
"""
from __future__ import annotations

import asyncio
import inspect
import os
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from tests.support import business_today
from app.api.v1 import settlements as confirm_router
from app.core.auth import CurrentUser, create_access_token
from app.core.database import get_session
from app.main import app
from app.models.address import Address
from app.models.audit_log import AuditLog
from app.models.base import Base
from app.models.catalog import ServiceCategory, ServiceItem
from app.models.enums import (
    MasterStatus,
    OperatorType,
    OrderStatus,
    PayStatus,
    SettlementStatus,
    UserRole,
)
from app.models.order import Order, OrderStatusLog
from app.models.provider import Master, ServiceProvider
from app.models.schedule_slot import ScheduleSlot
from app.models.settlement import Settlement, SettlementItem
from app.models.user import User
from app.services import settle as settle_service
from app.services.errors import (
    SettlementForbiddenError,
    SettlementInvariantError,
    SettlementNotFoundError,
)
from app.services.settle import confirm_settlement
from support import Rendezvous

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


# ---------------------------------------------------------------------
# 并发测试的会合点
# ---------------------------------------------------------------------


def _touches_settlement(statement) -> bool:
    """判断这条语句是不是作用在 settlement 表上（SELECT 或 UPDATE）。

    SELECT 按 ORM 实体判断，不能按语句文本里有没有 "settlement"——
    settlement_item 表的名字里就带着它。
    """
    if isinstance(statement, Select):
        try:
            return statement.column_descriptions[0].get("entity") is Settlement
        except Exception:  # noqa: BLE001 - 认不出来就当不是
            return False
    table = getattr(statement, "table", None)
    return table is not None and getattr(table, "name", None) == "settlement"


class SpySession:
    """记录 session 上发生过什么，用来断言「根本没碰库」。

    只盯两件事：开过几次事务（begin）、发过几条语句（execute）。

    为什么两样都要盯：只数 SQL 语句不够——asyncpg 的 BEGIN 是隐式的，
    不走 cursor execute，所以「先开事务再抛 403」这种写法在语句计数上
    看不出来，但事务一开就已经连上库了。「角色不对就连事务都不该开」，
    所以 begins 也得是 0。
    """

    def __init__(self, session) -> None:
        self._session = session
        self.begins = 0
        self.statements: list = []

    def begin(self):
        self.begins += 1
        return self._session.begin()

    async def execute(self, statement, *args, **kwargs):
        self.statements.append(statement)
        return await self._session.execute(statement, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._session, name)


class SettlementRendezvousSession:
    """在「第一次碰到 settlement 表」处会合的会话包装。

    会合点落在**发出**那条 UPDATE 之前：两个 UPDATE 同时在飞，
    由行锁裁决谁赢。

    放在「执行之后」会合会死锁：后一个 UPDATE 等前一个的行锁，
    前一个又卡在会合点等后一个。
    """

    def __init__(self, session, rendezvous: Rendezvous) -> None:
        self._session = session
        self._rendezvous = rendezvous
        self._armed = True

    async def execute(self, statement, *args, **kwargs):
        if self._armed and _touches_settlement(statement):
            # 每个会话只拦一次：拦第二次会把自己也卡住
            self._armed = False
            await self._rendezvous.wait()
            return await self._session.execute(statement, *args, **kwargs)
        return await self._session.execute(statement, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._session, name)

# ---------------------------------------------------------------------
# 种子数据里的 id
# ---------------------------------------------------------------------

PROVIDER_ID = 1
FINANCE_USER_ID = 2  # 平台财务
OPS_USER_ID = 3  # 平台运营（不是财务）
CUSTOMER_USER_ID = 4
ADMIN_USER_ID = 6  # 平台管理员（能看结算单列表，但不能确认）

MASTER_ID = 1
MASTER_USER_ID = 5

SETTLEMENT_ID = 1
SETTLEMENT_ITEM_ORDER_IDS = (1, 2)  # 这张结算单覆盖的两笔订单
# 另一张结算单：明细里的订单不在「待结算」状态（数据坏了），
# 用来验证「关联订单没全部流转就整体回滚」
BROKEN_SETTLEMENT_ID = 2
BROKEN_SETTLEMENT_ORDER_ID = 3

MISSING_SETTLEMENT_ID = 999999

ORDER_NO_1 = "OTO20260401000001"
ORDER_NO_2 = "OTO20260401000002"
ORDER_NO_3 = "OTO20260401000003"


def _confirm_url(settlement_id: int) -> str:
    return "/api/v1/settlements/{}/confirm".format(settlement_id)


def _auth_header(user_id: int, role: UserRole) -> dict[str, str]:
    token = create_access_token(user_id, role, None)
    return {"Authorization": "Bearer {}".format(token)}


def _finance_header() -> dict[str, str]:
    return _auth_header(FINANCE_USER_ID, UserRole.PLATFORM_FINANCE)


def _ops_header() -> dict[str, str]:
    return _auth_header(OPS_USER_ID, UserRole.PLATFORM_OPS)


def _admin_header() -> dict[str, str]:
    return _auth_header(ADMIN_USER_ID, UserRole.PLATFORM_ADMIN)


def _customer_header() -> dict[str, str]:
    return _auth_header(CUSTOMER_USER_ID, UserRole.USER)


# =====================================================================
# 单元测试：接口契约与 service 边界
# =====================================================================


def test_confirm_service_signature_has_no_operator_field() -> None:
    """确认人只能来自 CurrentUser，签名里不能有 confirmed_by 之类的参数。

    客户端自报「我替谁确认」就是自选身份（R1），所以这个参数传不进来。
    """
    parameters = inspect.signature(confirm_settlement).parameters
    assert "confirmed_by" not in parameters
    assert "user_id" not in parameters
    assert "operator_id" not in parameters
    assert "current" in parameters
    assert "settlement_id" in parameters


def test_settlement_forbidden_maps_to_403() -> None:
    """角色不对 -> 403。"""
    from app.api.v1.errors import status_for

    assert status_for(SettlementForbiddenError("没有权限")) == 403


def test_settlement_not_found_maps_to_404() -> None:
    """结算单不存在 / 已确认 -> 404（两种情况同构）。"""
    from app.api.v1.errors import status_for

    assert status_for(SettlementNotFoundError("没有")) == 404


def test_settlement_invariant_maps_to_500() -> None:
    """内部一致性被打破 -> 500（服务端 bug，不是客户端的问题）。"""
    from app.api.v1.errors import status_for

    assert status_for(SettlementInvariantError("坏了")) == 500


def test_confirm_uses_finance_operator_type() -> None:
    """确认留痕的操作方类型是 PLATFORM_FINANCE。"""
    source = inspect.getsource(settle_service)
    assert "OperatorType.PLATFORM_FINANCE" in source


def test_confirm_url_shape() -> None:
    """路由挂在 /api/v1/settlements/{id}/confirm 上。

    从 OpenAPI 文档里取路径：这个 FastAPI 版本的 app.routes 里
    装的是路由包装对象，取不到 path，得走 openapi()。
    """
    paths = app.openapi()["paths"]
    assert "/api/v1/settlements/{settlement_id}/confirm" in paths
    assert "post" in paths["/api/v1/settlements/{settlement_id}/confirm"]


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
async def seeded(db):
    """种一个服务商、一个平台财务账号、两笔「待结算」订单、一张待结算结算单。"""
    maker = async_sessionmaker(db, class_=AsyncSession, expire_on_commit=False)
    tomorrow = business_today() + timedelta(days=1)
    now = datetime.now(timezone.utc)
    async with maker() as session:
        session.add(
            ServiceProvider(
                id=PROVIDER_ID,
                name="服务商甲",
                contact_phone="13800000001",
                commission_rate=Decimal("0.2000"),
            )
        )
        await session.flush()

        session.add_all(
            [
                User(
                    id=FINANCE_USER_ID,
                    phone="13900000002",
                    role=UserRole.PLATFORM_FINANCE,
                ),
                User(id=OPS_USER_ID, phone="13900000003", role=UserRole.PLATFORM_OPS),
                User(id=CUSTOMER_USER_ID, phone="13900000004", role=UserRole.USER),
                User(id=MASTER_USER_ID, phone="13900000005", role=UserRole.MASTER),
                User(id=ADMIN_USER_ID, phone="13900000006", role=UserRole.PLATFORM_ADMIN),
            ]
        )
        await session.flush()

        session.add(ServiceCategory(id=1, name="测试分类"))
        await session.flush()
        session.add(
            ServiceItem(
                id=2,
                category_id=1,
                name="测试服务项",
                base_price=Decimal("100.00"),
                duration_min=60,
            )
        )
        await session.flush()

        session.add(
            Address(
                id=3,
                user_id=CUSTOMER_USER_ID,
                contact="张三",
                phone="13900000004",
                region="北京",
                detail="某街道 1 号",
            )
        )
        await session.flush()

        session.add(
            ScheduleSlot(
                id=4,
                item_id=2,
                date=tomorrow,
                start_time=time(9, 0),
                end_time=time(12, 0),
                capacity=5,
            )
        )
        await session.flush()

        session.add(
            Master(
                id=MASTER_ID,
                provider_id=PROVIDER_ID,
                user_id=MASTER_USER_ID,
                real_name="张师傅",
                status=MasterStatus.ACTIVE,
            )
        )
        await session.flush()

        def _order(order_id: int, order_no: str, amount: Decimal) -> Order:
            return Order(
                id=order_id,
                order_no=order_no,
                user_id=CUSTOMER_USER_ID,
                provider_id=PROVIDER_ID,
                master_id=MASTER_ID,
                address_id=3,
                item_id=2,
                slot_id=4,
                amount=amount,
                status=OrderStatus.PENDING_SETTLE,
                pay_status=PayStatus.PAID,
                paid_at=now - timedelta(days=3),
                dispatched_at=now - timedelta(days=3),
                accepted_at=now - timedelta(days=3),
                completed_at=now - timedelta(days=3),
                updated_at=now - timedelta(days=3),
            )

        session.add_all(
            [
                _order(1, ORDER_NO_1, Decimal("100.00")),
                _order(2, ORDER_NO_2, Decimal("50.00")),
            ]
        )
        # 第三笔订单卡在「已完成」：它被 BROKEN_SETTLEMENT_ID 那张结算单
        # 的明细引用着，但状态还没到「待结算」——数据坏了的情形
        broken_order = _order(BROKEN_SETTLEMENT_ORDER_ID, ORDER_NO_3, Decimal("30.00"))
        broken_order.status = OrderStatus.COMPLETED
        session.add(broken_order)
        await session.flush()

        # 合计 150，佣金 20% = 30，实收 120
        session.add(
            Settlement(
                id=SETTLEMENT_ID,
                provider_id=PROVIDER_ID,
                period_start=(now - timedelta(days=3)).date(),
                period_end=(now - timedelta(days=2)).date(),
                total_amount=Decimal("150.00"),
                commission_amount=Decimal("30.00"),
                net_amount=Decimal("120.00"),
                status=SettlementStatus.PENDING,
            )
        )
        await session.flush()

        session.add_all(
            [
                SettlementItem(
                    settlement_id=SETTLEMENT_ID,
                    order_id=order_id,
                    amount=amount,
                )
                for order_id, amount in (
                    (SETTLEMENT_ITEM_ORDER_IDS[0], Decimal("100.00")),
                    (SETTLEMENT_ITEM_ORDER_IDS[1], Decimal("50.00")),
                )
            ]
        )
        await session.flush()

        # 数据坏了的那张结算单：明细指向一笔还停在「已完成」的订单
        session.add(
            Settlement(
                id=BROKEN_SETTLEMENT_ID,
                provider_id=PROVIDER_ID,
                # 周期必须与 SETTLEMENT_ID 那张不同：
                # (provider_id, period_start, period_end) 是唯一的
                period_start=(now - timedelta(days=10)).date(),
                period_end=(now - timedelta(days=9)).date(),
                total_amount=Decimal("30.00"),
                commission_amount=Decimal("6.00"),
                net_amount=Decimal("24.00"),
                status=SettlementStatus.PENDING,
            )
        )
        await session.flush()
        session.add(
            SettlementItem(
                settlement_id=BROKEN_SETTLEMENT_ID,
                order_id=BROKEN_SETTLEMENT_ORDER_ID,
                amount=Decimal("30.00"),
            )
        )
        await session.flush()
        await session.commit()
    return True


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
async def spy_api_client(db):
    """带「间谍」的 HTTP 客户端。

    额外记录每个请求的 session 开过几次事务、发过几条语句，
    用来断言「角色不对的时候连库都没碰」。
    """
    maker = async_sessionmaker(db, class_=AsyncSession, expire_on_commit=False)
    spies: list[SpySession] = []

    async def override_get_session():
        async with maker() as session:
            spy = SpySession(session)
            spies.append(spy)
            yield spy

    app.dependency_overrides[get_session] = override_get_session
    try:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as http_client:
            yield http_client, spies
    finally:
        app.dependency_overrides.pop(get_session, None)


def _maker(db) -> async_sessionmaker:
    return async_sessionmaker(db, class_=AsyncSession, expire_on_commit=False)


async def _settlement_of(db, settlement_id: int) -> Settlement:
    maker = _maker(db)
    async with maker() as session:
        return (
            await session.execute(
                select(Settlement).where(Settlement.id == settlement_id)
            )
        ).scalar_one()


async def _order_of(db, order_id: int) -> Order:
    maker = _maker(db)
    async with maker() as session:
        return (
            await session.execute(select(Order).where(Order.id == order_id))
        ).scalar_one()


async def _status_logs_of(db, order_id: int) -> list[OrderStatusLog]:
    maker = _maker(db)
    async with maker() as session:
        rows = (
            await session.execute(
                select(OrderStatusLog).where(OrderStatusLog.order_id == order_id)
            )
        ).scalars().all()
        return list(rows)


async def _audit_logs_of(db, *, target_id: int) -> list[AuditLog]:
    maker = _maker(db)
    async with maker() as session:
        rows = (
            await session.execute(
                select(AuditLog).where(AuditLog.target_id == target_id)
            )
        ).scalars().all()
        return list(rows)


# ---------------------------------------------------------------------
# 1. 确认 PENDING 结算单
# ---------------------------------------------------------------------


@pytest.mark.integration
async def test_confirm_pending_settlement(db, seeded, api_client) -> None:
    """确认一张待结算的结算单：单子转已确认，订单全转已结算，两处都留痕。"""
    response = await api_client.post(
        _confirm_url(SETTLEMENT_ID), headers=_finance_header()
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == SETTLEMENT_ID
    assert body["status"] == "CONFIRMED"
    assert Decimal(str(body["net_amount"])) == Decimal("120.00")
    assert body["confirmed_at"] is not None

    # 结算单：已确认，记了确认人和确认时间
    settlement = await _settlement_of(db, SETTLEMENT_ID)
    assert settlement.status == SettlementStatus.CONFIRMED
    assert settlement.confirmed_by == FINANCE_USER_ID
    assert settlement.confirmed_at is not None

    # 关联订单：全部转「已结算」
    for order_id in SETTLEMENT_ITEM_ORDER_IDS:
        order = await _order_of(db, order_id)
        assert order.status == OrderStatus.SETTLED

        # 每笔订单一条状态流转日志
        logs = await _status_logs_of(db, order_id)
        assert len(logs) == 1
        assert logs[0].from_status == OrderStatus.PENDING_SETTLE
        assert logs[0].to_status == OrderStatus.SETTLED
        assert logs[0].operator_type == OperatorType.PLATFORM_FINANCE
        assert logs[0].operator_id == FINANCE_USER_ID

    # 审计日志：一条，记的是结算单状态变更
    audit_logs = await _audit_logs_of(db, target_id=SETTLEMENT_ID)
    assert len(audit_logs) == 1
    audit = audit_logs[0]
    assert audit.target_type == "settlement"
    assert audit.target_id == SETTLEMENT_ID
    assert audit.field_name == "status"
    assert audit.old_value == "PENDING"
    assert audit.new_value == "CONFIRMED"
    assert audit.operator_type == OperatorType.PLATFORM_FINANCE
    assert audit.operator_id == FINANCE_USER_ID
    assert audit.provider_id == PROVIDER_ID


# ---------------------------------------------------------------------
# 2. 非财务角色 -> 403，且不碰库
# ---------------------------------------------------------------------


@pytest.mark.integration
async def test_non_finance_role_is_forbidden(db, seeded, spy_api_client) -> None:
    """不是 PLATFORM_FINANCE 就被挡住——在碰数据库之前就挡住。

    挡在库外：角色不对的账号连「这张结算单存不存在」都不该知道，
    所以连事务都不该开、一条 SQL 都不该发。
    """
    http_client, spies = spy_api_client

    response = await http_client.post(
        _confirm_url(SETTLEMENT_ID), headers=_ops_header()
    )
    customer_response = await http_client.post(
        _confirm_url(SETTLEMENT_ID), headers=_customer_header()
    )

    assert response.status_code == 403
    assert customer_response.status_code == 403

    # 两次请求各一个会话：都没开过事务、没发过一条语句
    assert len(spies) == 2
    for spy in spies:
        assert spy.begins == 0
        assert spy.statements == []

    # 数据一点没动
    settlement = await _settlement_of(db, SETTLEMENT_ID)
    assert settlement.status == SettlementStatus.PENDING
    assert settlement.confirmed_by is None
    assert settlement.confirmed_at is None

    assert await _audit_logs_of(db, target_id=SETTLEMENT_ID) == []
    for order_id in SETTLEMENT_ITEM_ORDER_IDS:
        order = await _order_of(db, order_id)
        assert order.status == OrderStatus.PENDING_SETTLE
        assert await _status_logs_of(db, order_id) == []


# ---------------------------------------------------------------------
# 3. 平台管理员 -> 403，挡在**路由层**（service 根本没被调用）
# ---------------------------------------------------------------------


@pytest.mark.integration
async def test_platform_admin_is_blocked_at_route_layer(
    db, seeded, spy_api_client, monkeypatch
) -> None:
    """平台管理员 -> 403，而且是**路由层**挡的：service 压根没被调用。

    管理员能看结算单列表（对账用），但确认结算是把钱定下来的动作，
    只归财务——看得到不等于确认得了。

    三道证据说明「死在路由层」：

    1. **service 间谍**：把路由层引用的 service 换成记调用的壳，
       断言一次都没被叫到（这一条最直接：service 没跑起来）。
    2. **间谍 session**：一次事务都没开、一条 SQL 都没发——
       没碰库，也就问不到「这张结算单存不存在」。
    3. **响应文案**：路由层的 403 是通用的 ``"Forbidden"``；
       service 层抛的 403 是 ``"当前角色不能确认结算单"``。
    """
    http_client, spies = spy_api_client

    # service 间谍：记下每一次调用
    calls: list[int] = []
    real_service = confirm_router.confirm_settlement_service

    async def spy_service(*args, **kwargs):
        calls.append(kwargs.get("settlement_id"))
        return await real_service(*args, **kwargs)

    monkeypatch.setattr(confirm_router, "confirm_settlement_service", spy_service)

    response = await http_client.post(
        _confirm_url(SETTLEMENT_ID), headers=_admin_header()
    )

    # service 没被调用
    assert calls == []

    assert response.status_code == 403
    assert response.json() == {"detail": "Forbidden"}

    # service 没被调用 -> 库一次都没碰
    assert len(spies) == 1
    assert spies[0].begins == 0
    assert spies[0].statements == []

    # 数据一点没动
    settlement = await _settlement_of(db, SETTLEMENT_ID)
    assert settlement.status == SettlementStatus.PENDING
    assert settlement.confirmed_by is None
    assert settlement.confirmed_at is None
    assert await _audit_logs_of(db, target_id=SETTLEMENT_ID) == []


# ---------------------------------------------------------------------
# 3b. service 层的守卫还在（纵深防御）：直接调 service 也拒
# ---------------------------------------------------------------------


class _NeverTouchedSession:
    """任何调用都炸的 session 替身。

    service 的角色守卫应该在**碰库之前**就抛错：
    真碰了库，这里会先炸出来（AssertionError），而不是让
    SettlementForbiddenError 抛出来——顺序反了就说明守卫失效了。
    """

    def __getattr__(self, name):
        raise AssertionError(
            "角色不对时 service 碰了库（访问了 {}）".format(name)
        )


async def test_service_guard_rejects_non_finance_before_touching_db() -> None:
    """service 层那道守卫还在：绕过路由层直接调，管理员照样被拒。

    路由层已经有 ``require_platform_finance``，service 里那道是
    **纵深防御**：service 可能被别处直接调用（定时任务、内部脚本），
    不该依赖路由层替它把关。
    """
    current = CurrentUser(
        user_id=ADMIN_USER_ID,
        role=UserRole.PLATFORM_ADMIN,
        provider_id=None,
    )

    with pytest.raises(SettlementForbiddenError):
        await confirm_settlement(
            _NeverTouchedSession(),  # type: ignore[arg-type]
            current=current,
            settlement_id=SETTLEMENT_ID,
        )


# ---------------------------------------------------------------------
# 4. 已确认再确认 -> 404（与「不存在」同构）
# ---------------------------------------------------------------------


@pytest.mark.integration
async def test_confirm_already_confirmed_returns_404(db, seeded, api_client) -> None:
    """已确认的结算单再确认一次 -> 404，不重复确认、不重复留痕。"""
    first = await api_client.post(
        _confirm_url(SETTLEMENT_ID), headers=_finance_header()
    )
    assert first.status_code == 200

    second = await api_client.post(
        _confirm_url(SETTLEMENT_ID), headers=_finance_header()
    )

    assert second.status_code == 404

    # 审计日志还是一条，状态流转日志还是每笔一条
    assert len(await _audit_logs_of(db, target_id=SETTLEMENT_ID)) == 1
    for order_id in SETTLEMENT_ITEM_ORDER_IDS:
        assert len(await _status_logs_of(db, order_id)) == 1


# ---------------------------------------------------------------------
# 5. 不存在的结算单 -> 404（与「已确认」同构）
# ---------------------------------------------------------------------


@pytest.mark.integration
async def test_missing_settlement_returns_404(db, seeded, api_client) -> None:
    """不存在的结算单 -> 404。

    和「已被确认」是同一个响应：调用方不能靠报错差异
    探测某张结算单存不存在、是什么状态。
    """
    missing_response = await api_client.post(
        _confirm_url(MISSING_SETTLEMENT_ID), headers=_finance_header()
    )
    assert missing_response.status_code == 404

    # 先把这张结算单确认掉，再确认一次 -> 「已确认」的 404
    assert (
        await api_client.post(
            _confirm_url(SETTLEMENT_ID), headers=_finance_header()
        )
    ).status_code == 200
    already_response = await api_client.post(
        _confirm_url(SETTLEMENT_ID), headers=_finance_header()
    )
    assert already_response.status_code == 404

    missing_body = missing_response.json()
    already_body = already_response.json()

    # 两种情况的响应完全同构：同样的字段、同样的文案，
    # 唯一的差别是客户端自己给的 id。
    assert set(missing_body) == set(already_body) == {"detail"}
    assert missing_body["detail"].startswith("结算单不存在")
    assert already_body["detail"].startswith("结算单不存在")
    # 文案里只有 id，没有状态、没有金额、没有服务商归属
    assert str(SETTLEMENT_ID) in already_body["detail"]
    assert str(MISSING_SETTLEMENT_ID) in missing_body["detail"]
    assert "PENDING" not in already_body["detail"]
    assert "CONFIRMED" not in already_body["detail"]


# ---------------------------------------------------------------------
# 6. 关联订单没全部流转 -> 整体回滚
# ---------------------------------------------------------------------


@pytest.mark.integration
async def test_orders_not_all_settled_rolls_back(db, seeded, api_client) -> None:
    """明细里的订单没全部流转到「已结算」-> 整体回滚，500。

    结算单、明细、订单状态、状态流转日志、审计日志在同一个事务里：
    只要有一笔订单没流转成功，整张结算单就不能被确认——
    宁可这次确认失败，也不能留下「结算单已确认、订单还挂在待结算」的半截状态。
    """
    response = await api_client.post(
        _confirm_url(BROKEN_SETTLEMENT_ID), headers=_finance_header()
    )

    # 服务端数据坏了，不是客户端的问题 -> 500
    assert response.status_code == 500

    # 整体回滚：结算单没被确认
    settlement = await _settlement_of(db, BROKEN_SETTLEMENT_ID)
    assert settlement.status == SettlementStatus.PENDING
    assert settlement.confirmed_by is None
    assert settlement.confirmed_at is None

    # 订单状态没动
    order = await _order_of(db, BROKEN_SETTLEMENT_ORDER_ID)
    assert order.status == OrderStatus.COMPLETED

    # 没有留下任何留痕
    assert await _audit_logs_of(db, target_id=BROKEN_SETTLEMENT_ID) == []
    assert await _status_logs_of(db, BROKEN_SETTLEMENT_ORDER_ID) == []


# ---------------------------------------------------------------------
# 7. 并发确认同一张 -> 成功 1 失败 1
# ---------------------------------------------------------------------


@pytest.mark.integration
async def test_concurrent_confirm_only_one_wins(db, seeded) -> None:
    """两个财务同时确认同一张结算单：只有一个成功，留痕只有一份。

    认领结算单用的是条件 UPDATE（WHERE id=? AND status='PENDING'），
    行锁 + 谓词重求值裁决并发：先拿到锁的一方赢，另一方等锁期间
    谓词已不成立（结算单已是「已确认」），认领不到 -> 404。

    会合点落在「第一次碰到 settlement 表」的位置（这里是那条 UPDATE），
    两个协程真的挤在同一时刻发起更新，而不是一个跑完了另一个才开始。
    """
    maker = _maker(db)
    rendezvous = Rendezvous()
    current = CurrentUser(
        user_id=FINANCE_USER_ID,
        role=UserRole.PLATFORM_FINANCE,
        provider_id=None,
    )

    async def _confirm() -> str:
        async with maker() as raw_session:
            session = SettlementRendezvousSession(raw_session, rendezvous)
            try:
                await confirm_settlement(
                    session, current=current, settlement_id=SETTLEMENT_ID
                )
                return "ok"
            except Exception as exc:  # noqa: BLE001 - 只取异常类型名做断言
                return type(exc).__name__

    results = await asyncio.gather(_confirm(), _confirm())

    assert sorted(results) == ["SettlementNotFoundError", "ok"]

    # 结算单只被确认了一次
    settlement = await _settlement_of(db, SETTLEMENT_ID)
    assert settlement.status == SettlementStatus.CONFIRMED

    # 审计日志只有一条
    assert len(await _audit_logs_of(db, target_id=SETTLEMENT_ID)) == 1

    # 订单状态流转日志每笔只有一条
    for order_id in SETTLEMENT_ITEM_ORDER_IDS:
        order = await _order_of(db, order_id)
        assert order.status == OrderStatus.SETTLED
        assert len(await _status_logs_of(db, order_id)) == 1
