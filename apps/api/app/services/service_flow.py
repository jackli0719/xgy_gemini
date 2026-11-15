"""服务流转 service：开工 / 完工 / 客户确认完成。

订单走完「派单 -> 接单」之后进入服务阶段，由三个动作推进：

- ``start_service``     师傅开工：ACCEPTED      -> IN_SERVICE
- ``finish_service``    师傅完工：IN_SERVICE    -> PENDING_CONFIRM
- ``confirm_complete``  客户确认：PENDING_CONFIRM -> COMPLETED

六条硬约束（每一条都有测试盯着）：

1. **身份不从入参取**。
   - start / finish 是师傅侧动作：``my_master_id`` 从 ``current.user_id``
     查 master 表得到（师傅的归属权威来源是 master 表，不是入参）。
   - confirm 是客户侧动作：``user_id`` 就是 ``current.user_id``。
   三个函数的签名里都没有 master_id / user_id 参数——不是「约定别传」，
   是「传不进来」。租户归属一旦能由客户端指定，隔离当场失效（R1）。
2. **条件 UPDATE，禁止读-改-写**：WHERE 同时限定**目标状态**和**归属**：

   - start:   ``order_no=? AND status='ACCEPTED'       AND master_id=:my_master_id``
   - finish:  ``order_no=? AND status='IN_SERVICE'     AND master_id=:my_master_id``
   - confirm: ``order_no=? AND status='PENDING_CONFIRM' AND user_id=:my_user_id``

   由数据库的行锁裁决并发，与 dispatch、master_action、place_order 同一套思路。
   归属也写进谓词（而不是查出来再比对），是为了让「不是我的单」与
   「状态不对」在同一条 UPDATE 里一起被否决——不存在检查与写入之间的窗口。
3. **rowcount == 0 一律 404 同构**：订单不存在 / 不是我的 / 状态不对 /
   等待行锁期间这一行被改走又改回，四种情况抛同一个异常、同一句话。
   调用方没法靠报错差异探测别人的订单存不存在、归谁、什么状态（R1）。
4. **状态流转必须经状态机**（R4），并在同一事务内写 order_status_log。
   operator_type：start / finish 是 MASTER，confirm 是 USER。
5. **时间字段**：completed_at 在 confirm 时写；表里**没有** started_at 列，
   开工时间用「IN_SERVICE 状态 + 状态流转日志」表达——不为了凑字段去加列。
6. **只有 ACTIVE 的师傅能开工 / 完工**：停用（DISABLED）、休假（ON_LEAVE）、
   未审核（PENDING）的师傅一律 409（``MasterNotDispatchableError``）。
   与派单、接单是同一条规则——服务商把师傅停用之后，他在哪一头都不该再干活。
   **客户确认不查这个**：确认权在客户手上（USER 角色），跟师傅状态无关。

事务边界：查身份、条件更新、写日志、回读订单在同一事务内，要么全成要么全不成。
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser
from app.domain.order_state import assert_transition
from app.models.enums import MasterStatus, OperatorType, OrderStatus, UserRole
from app.models.order import Order, OrderStatusLog
from app.models.provider import Master
from app.services.errors import (
    MasterNotDispatchableError,
    OrderNotFoundError,
    ServiceFlowForbiddenError,
    ServiceFlowInvariantError,
)

__all__ = ["confirm_complete", "finish_service", "start_service"]


# 留在状态流转日志里的原因。客户确认的原因由系统写死（客户没给理由的入口）。
START_REASON = "师傅开工"
FINISH_REASON = "师傅完工"
CONFIRM_REASON = "客户确认完成"

# 「不存在」「不是我的」「状态不对」共用这一条消息。
#
# 消息里只回客户端自己给的 order_no，不含订单归属、师傅、状态，
# 所以这几种失败在响应里完全一样，攻击者无法据此判断某个订单号是否真实存在、
# 是否归别人（R1）。
_ORDER_NOT_FOUND_DETAIL = "订单不存在：order_no={order_no}"


async def start_service(
    session: AsyncSession,
    *,
    current: CurrentUser,
    order_no: str,
) -> Order:
    """开工：订单从「已接单」流转到「服务中」，返回落库的订单。

    要求传入的 session 没有活动事务——本函数会自行管理事务生命周期。
    """
    _require_master_role(current)

    async with session.begin():
        master = await _resolve_master(session, current)
        # 师傅当前能不能干活：只有 ACTIVE 可以（停用 / 休假 / 未审核一律 409）。
        # 与派单、接单是同一条规则、同一个异常、同一句话。
        _require_active_master(master)

        order_id = await _claim_order(
            session,
            order_no=order_no,
            from_status=OrderStatus.ACCEPTED,
            to_status=OrderStatus.IN_SERVICE,
            owner_column=Order.master_id,
            owner_id=master.id,
            extra_values={},
        )

        # 防御性断言：条件 UPDATE 命中，说明这一行的状态确实是 ACCEPTED，
        # 到 IN_SERVICE 的流转必然合法。状态机仍是唯一事实来源，
        # 这里只是不让「谓词写错了」这件事静默过去。
        assert_transition(OrderStatus.ACCEPTED, OrderStatus.IN_SERVICE)

        _add_status_log(
            session,
            order_id=order_id,
            from_status=OrderStatus.ACCEPTED,
            to_status=OrderStatus.IN_SERVICE,
            operator_type=OperatorType.MASTER,
            operator_id=current.user_id,
            reason=START_REASON,
        )
        await session.flush()

        order = await _load_order(session, order_id)
        # 本会话写完这一行，回读必须是我们写的样子。不一致 = 服务端 bug。
        _assert_written_state(
            order,
            to_status=OrderStatus.IN_SERVICE,
            owner_column=Order.master_id,
            expected_owner_id=master.id,
        )

    return order


async def finish_service(
    session: AsyncSession,
    *,
    current: CurrentUser,
    order_no: str,
) -> Order:
    """完工：订单从「服务中」流转到「待确认」，返回落库的订单。

    完工后由客户确认（confirm_complete）才写 completed_at——
    师傅说「做完了」不等于订单完成。
    """
    _require_master_role(current)

    async with session.begin():
        master = await _resolve_master(session, current)
        # 同开工：不在岗的师傅不干活（409）
        _require_active_master(master)

        order_id = await _claim_order(
            session,
            order_no=order_no,
            from_status=OrderStatus.IN_SERVICE,
            to_status=OrderStatus.PENDING_CONFIRM,
            owner_column=Order.master_id,
            owner_id=master.id,
            extra_values={},
        )

        assert_transition(OrderStatus.IN_SERVICE, OrderStatus.PENDING_CONFIRM)

        _add_status_log(
            session,
            order_id=order_id,
            from_status=OrderStatus.IN_SERVICE,
            to_status=OrderStatus.PENDING_CONFIRM,
            operator_type=OperatorType.MASTER,
            operator_id=current.user_id,
            reason=FINISH_REASON,
        )
        await session.flush()

        order = await _load_order(session, order_id)
        _assert_written_state(
            order,
            to_status=OrderStatus.PENDING_CONFIRM,
            owner_column=Order.master_id,
            expected_owner_id=master.id,
        )

    return order


async def confirm_complete(
    session: AsyncSession,
    *,
    current: CurrentUser,
    order_no: str,
) -> Order:
    """客户确认完成：订单从「待确认」流转到「已完成」，并写 completed_at。

    归属判定用的是订单的客户（order.user_id），不是师傅：
    确认权在客户手上，师傅自己不能替客户点确认。
    """
    _require_user_role(current)

    async with session.begin():
        now = datetime.now(timezone.utc)

        order_id = await _claim_order(
            session,
            order_no=order_no,
            from_status=OrderStatus.PENDING_CONFIRM,
            to_status=OrderStatus.COMPLETED,
            owner_column=Order.user_id,
            owner_id=current.user_id,
            # 完工时间在这里落库：客户确认的那一刻才算真正做完
            extra_values={"completed_at": now},
        )

        assert_transition(OrderStatus.PENDING_CONFIRM, OrderStatus.COMPLETED)

        _add_status_log(
            session,
            order_id=order_id,
            from_status=OrderStatus.PENDING_CONFIRM,
            to_status=OrderStatus.COMPLETED,
            operator_type=OperatorType.USER,
            operator_id=current.user_id,
            reason=CONFIRM_REASON,
        )
        await session.flush()

        order = await _load_order(session, order_id)
        _assert_written_state(
            order,
            to_status=OrderStatus.COMPLETED,
            owner_column=Order.user_id,
            expected_owner_id=current.user_id,
        )

    return order


def _require_master_role(current: CurrentUser) -> None:
    """开工 / 完工是师傅侧动作，角色不对直接拒。

    失败在碰订单之前发生，所以不会泄露任何订单信息。
    """
    if current.role is not UserRole.MASTER:
        raise ServiceFlowForbiddenError("当前角色不能执行师傅侧服务动作")


def _require_user_role(current: CurrentUser) -> None:
    """确认完成是客户侧动作，角色不对直接拒。"""
    if current.role is not UserRole.USER:
        raise ServiceFlowForbiddenError("当前角色不能确认订单完成")


def _require_active_master(master: Master) -> None:
    """师傅当前能不能干活：只有 ACTIVE 可以。

    停用（DISABLED）、休假（ON_LEAVE）、未审核（PENDING）的师傅一律 409。
    与派单（dispatch）、接单（master_action）是同一条业务规则，
    所以抛的是同一个异常、同一句话——服务商把师傅停用之后，
    派单那头派不到他，他接不了单，也开不了工。

    **客户确认不查这个**：确认权在客户手上，跟师傅状态无关。
    """
    if master.status != MasterStatus.ACTIVE:
        raise MasterNotDispatchableError(
            "师傅当前不可接单：master_id={}".format(master.id)
        )


async def _resolve_master(session: AsyncSession, current: CurrentUser) -> Master:
    """从当前登录用户查出他对应的师傅身份。

    师傅的归属权威来源是 master 表，不是入参、也不是 user.provider_id：
    一个登录用户最多对应一个师傅身份（uq_master_user_id 唯一约束保证）。

    token 里带了 provider_id（服务商账号同时也是师傅）时，
    它必须与 master.provider_id 一致，否则这个账号的身份是错乱的，
    不能让它动订单。
    """
    master = (
        await session.execute(
            select(Master).where(Master.user_id == current.user_id)
        )
    ).scalar_one_or_none()
    if master is None:
        # 这个账号没有师傅身份。它看不到、也碰不了任何订单。
        raise ServiceFlowForbiddenError("当前账号没有师傅身份")
    if current.provider_id is not None and current.provider_id != master.provider_id:
        raise ServiceFlowForbiddenError("当前账号的师傅身份与服务商归属不一致")
    return master


async def _claim_order(
    session: AsyncSession,
    *,
    order_no: str,
    from_status: OrderStatus,
    to_status: OrderStatus,
    owner_column,
    owner_id: int,
    extra_values: dict,
) -> int:
    """条件 UPDATE：把「这单是归我的、且正等着这一步」写进 WHERE 谓词。

    返回被更新那行的 id；没命中就抛 OrderNotFoundError。

    不能读-改-写。两个请求同时推进同一笔订单时，读-改-写会这样坏掉：
      T1 读到 status='ACCEPTED' -> T2 也读到 status='ACCEPTED'
      -> 两边各自改一遍 -> 后提交的那个把前一个的覆盖掉（丢更新），
      并且写出两条状态流转日志。

    条件 UPDATE 把判定交给数据库：T2 的 UPDATE 会等 T1 的行锁，
    拿到锁后重新求值谓词，此时状态已经推进，谓词不成立，
    影响 0 行 —— 天然 fail-safe。与 dispatch、master_action、place_order 同一套思路。

    UPDATE ... RETURNING 同时拿到了被更新那行的 id：
    「没有返回行」与「rowcount == 0」是同一件事（没命中）。
    """
    values = {
        "status": to_status,
        # Core 的 UPDATE 不走 ORM 的 onupdate，得自己带上
        "updated_at": func.now(),
    }
    values.update(extra_values)

    result = await session.execute(
        update(Order)
        .where(
            Order.order_no == order_no,
            # 目标状态：只有正等着这一步的订单才动得了
            Order.status == from_status,
            # 归属：这一单是归我（师傅）/ 归这个客户的
            owner_column == owner_id,
        )
        .values(**values)
        .returning(Order.id)
    )
    row = result.first()
    if row is None:
        # 没命中。四种原因对调用方是同一件事——「这单现在轮不到你」：
        #   - 订单不存在
        #   - 不是我的（不是派给我的单 / 不是我下的单）
        #   - 状态不对
        #   - 等待行锁期间这一行被改走又改回
        # 统一 404，不让调用方靠报错差异探测订单存不存在、归谁（R1）。
        #
        # 刻意**不回查**：回查的结果不会改变对外响应（都是同一条 404），
        # 只会多一次往返。真 bug 的判定放在写入后的回读校验上
        # （_assert_written_state）。
        raise OrderNotFoundError(_ORDER_NOT_FOUND_DETAIL.format(order_no=order_no))

    return row[0]


def _assert_written_state(
    order: Order,
    *,
    to_status: OrderStatus,
    owner_column,
    expected_owner_id: int,
) -> None:
    """校验「本会话刚写的这一行，回读出来确实是我们写的样子」。

    条件 UPDATE 命中后，同一事务内回读一定是我们自己写进去的值。
    回读出来不一样，说明这一行的写入被别的东西改了（数据库触发器、
    谓词写歪、库里规则与模型不一致）——这是服务端 bug，不是业务失败，
    必须暴露成 500，不能伪装成「订单不存在」蒙混过去。
    """
    owner_value = getattr(order, owner_column.key)
    if order.status != to_status or owner_value != expected_owner_id:
        raise ServiceFlowInvariantError(
            "订单状态与本次写入不一致：order_no={}, status={}".format(
                order.order_no, getattr(order.status, "value", order.status)
            )
        )


def _add_status_log(
    session: AsyncSession,
    *,
    order_id: int,
    from_status: OrderStatus,
    to_status: OrderStatus,
    operator_type: OperatorType,
    operator_id: int,
    reason: str,
) -> None:
    """写一条状态流转日志（R4）。

    operator_type 由调用方显式给出：开工 / 完工是师傅侧动作（MASTER），
    客户确认是用户侧动作（USER）。
    """
    session.add(
        OrderStatusLog(
            order_id=order_id,
            from_status=from_status,
            to_status=to_status,
            operator_type=operator_type,
            operator_id=operator_id,
            reason=reason,
        )
    )


async def _load_order(session: AsyncSession, order_id: int) -> Order:
    """回读落库后的订单。

    同一事务内、我们自己的 UPDATE 之后读到的一定是自己写进去的值。
    """
    return (
        await session.execute(select(Order).where(Order.id == order_id))
    ).scalar_one()
