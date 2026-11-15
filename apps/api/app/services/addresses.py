"""用户地址管理 service（增删改查）。

三条硬约束（每一条都有测试盯着）：

1. **身份只从 token 来**（R5）：所有读写都带 ``Address.user_id == 当前用户``
   这个谓词，接口层根本没有「改谁的地址」这种入参。
   「地址不存在」与「地址不属于你」共用同一个异常、同一句话（404 同构），
   调用方没法靠错误差异探测别人的地址存不存在、归谁。
2. **写操作用条件 UPDATE / 带谓词的 SELECT**：改和删都是先按
   ``(id, user_id)`` 查出来再改，查不到就是 404。
   不做「先按 id 查出来、再判断归属」——那多一次往返，还多一个能写错的分支。
3. **事务内只做这一件事**：写操作自己管事务（``async with session.begin()``），
   不依赖调用方记得提交。

异常：复用 ``app.services.errors.AddressNotFoundError``——
它的语义正是「地址不存在，或不属于当前用户」，且已经映射成 404。
下单链路（引用地址）和地址管理链路共用同一个 404 语义，
调用方在两个接口上看到的文案也一样，不会以为「换个接口就能绕过归属检查」。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.address import Address
from app.services.errors import AddressInUseError, AddressNotFoundError

__all__ = [
    "AddressRow",
    "create_address",
    "delete_address",
    "list_addresses",
    "update_address",
]

# 「地址不存在」的文案模板。与下单链路（app.services.place_order）逐字一致，
# 方便前端按同一套文案处理，也保证「不存在」与「不属于你」返回同一句话。
_ADDRESS_NOT_FOUND_DETAIL = "地址不存在：address_id={address_id}"

# 「地址被订单引用」的文案。客户端据此提示用户「换个地址 / 先处理订单」。
_ADDRESS_IN_USE_DETAIL = "地址已被订单使用，无法删除"

# order 表指向 address 的外键约束名。
#
# 迁移 0001 与模型里这条 FK 都没有显式命名，用的是 PostgreSQL 的默认命名
# （<表>_<列>_fkey）。哪天真给它起了名字，这里要同步改——
# 认错了约束就会把「别的完整性冲突」误报成「地址被占用」。
ORDER_ADDRESS_FK_CONSTRAINT = "order_address_id_fkey"

# 兜底解析约束名：PostgreSQL 的错误消息形如
# update or delete on table "address" violates foreign key constraint
# "order_address_id_fkey" on table "order"
_CONSTRAINT_PATTERN = re.compile(r'constraint "([^"]+)"')


@dataclass(frozen=True)
class AddressRow:
    """一条地址（不包含归属字段）。"""

    id: int
    contact: str
    phone: str
    region: str
    detail: str


async def list_addresses(session: AsyncSession, *, user_id: int) -> list[AddressRow]:
    """返回当前用户的全部地址。

    过滤条件里带着 ``user_id``：这是 R5 的落点——列表只可能返回自己的地址。
    排序按 id 升序（先建的在前面），同一份数据每次返回的顺序一样。
    """
    rows = (
        await session.execute(
            select(
                Address.id,
                Address.contact,
                Address.phone,
                Address.region,
                Address.detail,
            )
            .where(Address.user_id == user_id)
            .order_by(Address.id)
        )
    ).all()
    return [AddressRow(*row) for row in rows]


async def create_address(
    session: AsyncSession,
    *,
    user_id: int,
    contact: str,
    phone: str,
    region: str,
    detail: str,
) -> AddressRow:
    """新建一条属于当前用户的地址，返回落库后的地址。

    ``user_id`` 由调用方从 token 里取，客户端无从干预（R1）。
    """
    async with session.begin():
        address = Address(
            user_id=user_id,
            contact=contact,
            phone=phone,
            region=region,
            detail=detail,
        )
        session.add(address)
        await session.flush()
        return AddressRow(
            id=address.id,
            contact=address.contact,
            phone=address.phone,
            region=address.region,
            detail=address.detail,
        )


async def update_address(
    session: AsyncSession,
    *,
    user_id: int,
    address_id: int,
    contact: str,
    phone: str,
    region: str,
    detail: str,
) -> AddressRow:
    """修改当前用户的某条地址（整体替换四个字段）。

    地址不存在 / 不属于当前用户 -> AddressNotFoundError（404，两种情况同构）。
    """
    async with session.begin():
        address = await _get_own_address(session, user_id=user_id, address_id=address_id)
        address.contact = contact
        address.phone = phone
        address.region = region
        address.detail = detail
        await session.flush()
        return AddressRow(
            id=address.id,
            contact=address.contact,
            phone=address.phone,
            region=address.region,
            detail=address.detail,
        )


async def delete_address(
    session: AsyncSession, *, user_id: int, address_id: int
) -> None:
    """删除当前用户的某条地址。

    地址不存在 / 不属于当前用户 -> AddressNotFoundError（404，两种情况同构）。

    地址被订单引用时**不能删**：order.address_id 上是 RESTRICT 外键，
    而表里没有地址快照列（订单只存 address_id），删掉地址订单就指不回它了。
    数据库会挡下这次删除（外键冲突），这里把它翻译成 409
    （AddressInUseError）——「换个地址 / 先处理订单再来」是可行的应对，
    报成 500 会让调用方以为重发有用。
    """
    async with session.begin():
        address = await _get_own_address(session, user_id=user_id, address_id=address_id)
        try:
            await session.delete(address)
            # delete() 只是把对象标记为待删，真正的 DELETE 要 flush 才发出去；
            # 不 flush 的话外键冲突要到提交时才炸，那时响应已经出去了。
            await session.flush()
        except IntegrityError as exc:
            if not _is_order_address_violation(exc):
                # 别的完整性冲突（主键、CHECK 等）跟「地址被占用」无关，
                # 原样抛出，别把它伪装成 409。
                raise
            raise AddressInUseError(_ADDRESS_IN_USE_DETAIL) from None


async def _get_own_address(
    session: AsyncSession, *, user_id: int, address_id: int
) -> Address:
    """按 (id, user_id) 取一条地址；取不到就抛 404。

    谓词里同时带 id 和 user_id：查不到只有两种可能（不存在 / 不是你的），
    两种都返回同一句话，调用方无法靠差异探测（R5）。
    """
    address = (
        await session.execute(
            select(Address).where(
                Address.id == address_id,
                Address.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if address is None:
        raise AddressNotFoundError(
            _ADDRESS_NOT_FOUND_DETAIL.format(address_id=address_id)
        )
    return address


def _is_order_address_violation(exc: IntegrityError) -> bool:
    """判断这个完整性冲突是不是「订单还引用着这条地址」。

    只认 order.address_id 那一条外键：别的冲突（主键、CHECK、别的外键）
    重试没有意义，静默吞掉会把真正的错误藏起来。
    """
    orig = getattr(exc, "orig", None)
    constraint = getattr(orig, "constraint_name", None)
    if constraint is None:
        # 驱动没给约束名时从消息里兜底解析
        match = _CONSTRAINT_PATTERN.search(str(exc))
        constraint = match.group(1) if match else None
    return constraint == ORDER_ADDRESS_FK_CONSTRAINT
