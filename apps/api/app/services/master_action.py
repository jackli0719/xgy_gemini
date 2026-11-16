"""师傅接单 / 拒单 service。

师傅对「派给自己」的订单做出响应：接单（转「已接单」）或拒单（退回「待派单」）。

六条硬约束（每一条都有测试盯着）：

1. **师傅身份从 CurrentUser 查 master 表得到**，不从入参取。
   两个函数的签名里都没有 master_id 参数——不是「约定别传」，是「传不进来」。
   订单用 order_no 定位（不是 order_id）：师傅手上拿到的是订单号。
2. **条件 UPDATE，禁止读-改-写**：把「这单还派给我、还等着我响应」写进
   WHERE 谓词，由数据库的行锁裁决并发。与 dispatch、place_order 同一套思路。
3. **失败一律 404 同构**：订单不存在、不是派给我的、状态不对、
   以及「等待行锁期间这一行被改走又改回」，四种情况抛同一个异常、
   同一句话。调用方没法靠报错差异探测别家的单（R1）。
   第四种尤其要当成普通失败：那一行只是变了又变回来，
   对调用方就是「状态变了，重试」，不是服务端 bug。
4. **状态流转必须经状态机**（R4），并在同一事务内写 order_status_log，
   operator_type = MASTER；拒单的 reason 落进日志。
5. **拒单只清 master_id，不动 provider_id**：订单是客户付给这个服务商的，
   师傅拒单不改变归属服务商——否则订单会从服务商手里漏出去（R1）。
   订单退回本商的「待派单」池，可以重新派单
   （见 dispatch 里「归属不变式」对这两种形态的区分）。
6. **只有 ACTIVE 的师傅能接单**：停用（DISABLED）、休假（ON_LEAVE）、
   未审核（PENDING）的师傅接不了新单（409）。
   **拒单不拦**：停用的师傅手上可能还有派给他的单，
   让他退回去才是出路——挡住拒单等于把单卡死在他手上。

事务边界：查师傅、条件更新、写日志、回读订单在同一事务内，要么全成要么全不成。
"""
from __future__ import annotations

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser
from app.core.timezone import now_utc
from app.domain.order_state import assert_transition
from app.models.enums import MasterStatus, OperatorType, OrderStatus
from app.models.order import Order, OrderStatusLog
from app.models.provider import Master
from app.services.errors import (
    MasterActionForbiddenError,
    MasterActionInvariantError,
    MasterNotDispatchableError,
    OrderNotFoundError,
)

__all__ = ["accept_order", "reject_order"]


# 接单留在日志里的原因。拒单的原因由师傅自己给，原样落库。
ACCEPT_REASON = "师傅接单"

# 「不存在」「不是派给我的」「状态不对」共用这一条消息。
#
# 消息里只回客户端自己给的 order_no，不含订单归属、师傅、状态，
# 所以这三种失败在响应里完全一样，攻击者无法据此判断某个订单号是否真实存在、
# 是否派给了别人（R1）。
_ORDER_NOT_FOUND_DETAIL = "订单不存在：order_no={order_no}"


async def accept_order(
    session: AsyncSession,
    *,
    order_no: str,
    current_user: CurrentUser,
) -> Order:
    """接单：订单从「待接单」流转到「已接单」，返回落库的订单。

    要求传入的 session 没有活动事务——本函数会自行管理事务生命周期。
    """
    async with session.begin():
        master = await _resolve_master(session, current_user)
        # 师傅当前能不能接单：只有 ACTIVE 可以。
        # 停用 / 休假 / 未审核的师傅不接新单（409）。
        #
        # 这条与派单那头是同一条业务规则（「能接单的师傅是在岗的师傅」），
        # 所以抛的是同一个异常、同一句话（见 app.services.errors）：
        # 服务商把师傅停用之后，派单那头派不到他，他自己这头也接不了。
        #
        # **拒单不查这个**：停用的师傅手上可能还有派给他的单，
        # 让他退回去才是出路，挡住拒单等于把单卡死在他手上。
        if master.status != MasterStatus.ACTIVE:
            raise MasterNotDispatchableError(
                "师傅当前不可接单：master_id={}".format(master.id)
            )
        now = now_utc()

        order_id = await _claim_order(
            session,
            order_no=order_no,
            master_id=master.id,
            to_status=OrderStatus.ACCEPTED,
            extra_values={"accepted_at": now},
        )

        # 防御性断言：条件 UPDATE 命中，说明这一行的状态确实是 PENDING_ACCEPT，
        # 到 ACCEPTED 的流转必然合法。状态机仍是唯一事实来源，
        # 这里只是不让「谓词写错了」这件事静默过去。
        assert_transition(OrderStatus.PENDING_ACCEPT, OrderStatus.ACCEPTED)

        _add_status_log(
            session,
            order_id=order_id,
            to_status=OrderStatus.ACCEPTED,
            current_user=current_user,
            reason=ACCEPT_REASON,
        )
        await session.flush()

        order = await _load_order(session, order_id)
        # 本会话写完这一行，回读必须是我们写的样子。不一致 = 服务端 bug。
        _assert_written_state(
            order,
            to_status=OrderStatus.ACCEPTED,
            expected_master_id=master.id,
        )

    return order


async def reject_order(
    session: AsyncSession,
    *,
    order_no: str,
    reason: str,
    current_user: CurrentUser,
) -> Order:
    """拒单：订单退回「待派单」，清空承接师傅，返回落库的订单。

    **不动 provider_id**：订单归属哪个服务商与师傅接不接单无关。
    清掉 provider_id 会让订单从服务商手里漏出去（R1）。
    退回后订单仍在本商的待派单池里，可以重新派单。

    要求传入的 session 没有活动事务——本函数会自行管理事务生命周期。
    """
    async with session.begin():
        master = await _resolve_master(session, current_user)

        order_id = await _claim_order(
            session,
            order_no=order_no,
            master_id=master.id,
            to_status=OrderStatus.PENDING_DISPATCH,
            # 拒单：清空承接师傅，订单回到「谁都能接」的状态
            extra_values={"master_id": None},
        )

        assert_transition(OrderStatus.PENDING_ACCEPT, OrderStatus.PENDING_DISPATCH)

        _add_status_log(
            session,
            order_id=order_id,
            to_status=OrderStatus.PENDING_DISPATCH,
            current_user=current_user,
            reason=reason,
        )
        await session.flush()

        order = await _load_order(session, order_id)
        # 本会话写完这一行，回读必须是我们写的样子。不一致 = 服务端 bug。
        _assert_written_state(
            order,
            to_status=OrderStatus.PENDING_DISPATCH,
            expected_master_id=None,
        )

    return order


async def _resolve_master(session: AsyncSession, current_user: CurrentUser) -> Master:
    """从当前登录用户查出他对应的师傅身份。

    师傅的归属权威来源是 master 表，不是 user.provider_id：
    一个登录用户最多对应一个师傅身份（uq_master_user_id 唯一约束保证）。
    所以这里按 current_user.user_id 查 master，而不是从入参拿 master_id。

    token 里带了 provider_id（服务商账号同时也是师傅）时，
    它必须与 master.provider_id 一致，否则这个账号的身份是错乱的，
    不能让它动订单。
    """
    master = (
        await session.execute(
            select(Master).where(Master.user_id == current_user.user_id)
        )
    ).scalar_one_or_none()
    if master is None:
        # 这个账号没有师傅身份。它看不到、也碰不了任何订单。
        raise MasterActionForbiddenError("当前账号没有师傅身份")
    if current_user.provider_id is not None and current_user.provider_id != master.provider_id:
        raise MasterActionForbiddenError("当前账号的师傅身份与服务商归属不一致")
    return master


async def _claim_order(
    session: AsyncSession,
    *,
    order_no: str,
    master_id: int,
    to_status: OrderStatus,
    extra_values: dict,
) -> int:
    """条件 UPDATE：把「这单还派给我、还等着我响应」写进 WHERE 谓词。

    返回被更新那行的 id；没命中就抛 OrderNotFoundError。

    不能读-改-写。两个请求同时接同一单时，读-改-写会这样坏掉：
      T1 读到 status='PENDING_ACCEPT' -> T2 也读到 status='PENDING_ACCEPT'
      -> 两边各自改一遍 -> 后提交的那个把前一个的覆盖掉（丢更新），
      并且写出两条状态流转日志。

    条件 UPDATE 把判定交给数据库：T2 的 UPDATE 会等 T1 的行锁，
    拿到锁后重新求值谓词，此时状态已经推进，谓词不成立，
    影响 0 行 —— 天然 fail-safe。与 dispatch、place_order._reserve_slot 同一套思路。

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
            Order.status == OrderStatus.PENDING_ACCEPT,
            # 「派给我」：订单当前的承接师傅是我
            Order.master_id == master_id,
        )
        .values(**values)
        .returning(Order.id)
    )
    row = result.first()
    if row is None:
        # 没命中。四种原因对调用方是同一件事——「这单现在轮不到你」：
        #   - 订单不存在
        #   - 不是派给我的
        #   - 状态不对（已接单 / 已拒单 / 已派单待响应）
        #   - 等待行锁期间这一行被改走又改回（拒单后重新派回同一师傅）
        # 统一 404，不让调用方靠报错差异探测订单存不存在、派给了谁（R1）。
        #
        # 刻意**不回查**：回查的结果不会改变对外响应（都是同一条 404），
        # 只会多一次往返。而「谓词写错了」这种真 bug 靠回查也分不出来——
        # 改走又改回的 ABA 与写错的谓词，在回查里长得一模一样。
        # 真 bug 的判定放在写入后的回读校验上（_assert_written_state）：
        # 那里能确定是「我们自己写的这一行，回读却不是我们写的样子」。
        raise OrderNotFoundError(_ORDER_NOT_FOUND_DETAIL.format(order_no=order_no))

    order_id = row[0]
    return order_id


def _assert_written_state(
    order: Order, *, to_status: OrderStatus, expected_master_id: int | None
) -> None:
    """校验「本会话刚写的这一行，回读出来确实是我们写的样子」。

    条件 UPDATE 命中后，同一事务内回读一定是我们自己写进去的值。
    回读出来不一样，说明这一行的写入被别的东西改了（数据库触发器、
    谓词写歪、库里规则与模型不一致）——这是服务端 bug，不是业务失败，
    必须暴露成 500，不能伪装成「订单不存在」蒙混过去。

    这是 MasterActionInvariantError 唯一的用途：
    「本事务内本会话改过该行，回读仍不一致」。
    """
    if order.status != to_status or order.master_id != expected_master_id:
        raise MasterActionInvariantError(
            "订单状态与本次写入不一致：order_no={}, status={}".format(
                order.order_no, getattr(order.status, "value", order.status)
            )
        )


def _add_status_log(
    session: AsyncSession,
    *,
    order_id: int,
    to_status: OrderStatus,
    current_user: CurrentUser,
    reason: str,
) -> None:
    """写一条状态流转日志（R4）。

    操作方类型固定是 MASTER：接单 / 拒单都是师傅侧动作。
    operator_id 记登录账号的 user_id（master 表的 user_id 与之一致）。
    """
    session.add(
        OrderStatusLog(
            order_id=order_id,
            from_status=OrderStatus.PENDING_ACCEPT,
            to_status=to_status,
            operator_type=OperatorType.MASTER,
            operator_id=current_user.user_id,
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
