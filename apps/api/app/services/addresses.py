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

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.address import Address
from app.services.errors import AddressNotFoundError

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

    删掉地址不会影响已存在的订单：订单里存的是 address_id 与下单时的快照，
    历史订单要显示当时的地址，靠的是订单自己的记录，不是地址表。
    """
    async with session.begin():
        address = await _get_own_address(session, user_id=user_id, address_id=address_id)
        await session.delete(address)


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
