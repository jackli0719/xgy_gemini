"""登录 service（手机号 + 验证码）。

**MVP 占位**：短信验证码不接网关，固定值来自配置
（``settings.login_sms_code``，默认 123456）。接真实短信时只换这一个比对点，
其余流程（查用户 / 建用户 / 签 token）不变。

三条决定：

1. **验证码不对 -> 401**：登录失败就是失败，没有「半登录」这种中间态。
   文案统一成「验证码错误或已过期」，不区分「验证码写错」和「验证码过期」
   （对客户端来说都只能重发）。
2. **手机号没注册过就自动建号**：C 端「手机号 + 验证码」登录本来就是
   「登录即注册」——用户不该先注册再登录。建出来的账号是普通用户角色
   （``UserRole.USER``），没有服务商归属。
3. **只选标量列，不持有 ORM 对象**：读完用户就 ``rollback`` 结束只读事务，
   持有 ORM 对象的话，之后访问它的属性会触发 lazy load，在 async 下直接炸
   （见 app.services.place_order 里同一段注释）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import create_access_token
from app.core.config import settings
from app.models.enums import UserRole, UserStatus
from app.models.user import User

__all__ = [
    "InvalidLoginCodeError",
    "LoginResult",
    "LoginUserDisabledError",
    "login",
]

# user 表 phone 的唯一约束名（见 app.models.user 的 UniqueConstraint）。
# 只有这一种冲突才当成「别人已经建好同一个手机号」。
USER_PHONE_CONSTRAINT = "uq_user_phone"

# 兜底解析约束名：PostgreSQL 的错误消息形如
# duplicate key value violates unique constraint "uq_user_phone"
_CONSTRAINT_PATTERN = re.compile(r'constraint "([^"]+)"')


class LoginError(Exception):
    """登录失败的业务异常基类。"""


class InvalidLoginCodeError(LoginError):
    """验证码不对（写错 / 过期 / 压根不是本次的验证码）。

    不区分具体原因：对客户端来说这几种情况的应对都一样——重新发一条。
    """


class LoginUserDisabledError(LoginError):
    """账号已被禁用 / 封禁，不能登录。"""


@dataclass(frozen=True)
class LoginUserRow:
    """登录用户的标量快照（不持有 ORM 对象）。"""

    id: int
    nickname: str
    phone: str
    role: UserRole
    provider_id: int | None
    status: UserStatus


@dataclass(frozen=True)
class LoginResult:
    """登录成功的结果：token + 用户信息。"""

    token: str
    user: LoginUserRow


async def login(session: AsyncSession, *, phone: str, code: str) -> LoginResult:
    """校验验证码、找到（或建出）用户、签发 token。

    验证码不对 -> InvalidLoginCodeError；
    账号被禁用 -> LoginUserDisabledError。
    """
    if code != settings.login_sms_code:
        raise InvalidLoginCodeError("验证码错误或已过期")

    user = await _find_by_phone(session, phone)
    if user is None:
        user = await _create_user(session, phone)
    if user.status != UserStatus.ACTIVE:
        raise LoginUserDisabledError("账号已被禁用")

    token = create_access_token(user.id, user.role, user.provider_id)
    return LoginResult(token=token, user=user)


async def _find_by_phone(session: AsyncSession, phone: str) -> LoginUserRow | None:
    """按手机号找用户；没有就返回 None。

    只 select 标量列：拿到就 ``rollback`` 结束 autobegin 出来的只读事务，
    之后 session 里不留任何待提交的东西，写操作才能自己开事务。
    """
    row = (
        await session.execute(
            select(
                User.id,
                User.nickname,
                User.phone,
                User.role,
                User.provider_id,
                User.status,
            ).where(User.phone == phone)
        )
    ).one_or_none()
    await session.rollback()
    if row is None:
        return None
    return LoginUserRow(*row)


async def _create_user(session: AsyncSession, phone: str) -> LoginUserRow:
    """按手机号建一个新用户（登录即注册）。

    并发首次登录时可能撞上 phone 唯一约束：这时另一个请求已经建好了，
    重读一次用它的即可（两边的账号是同一个）。

    **只把 phone 唯一约束冲突当成「别人建好了」**：别的完整性冲突
    （比如主键撞了）说明数据有问题，原样抛出去，不在这里悄悄吞掉。
    """
    try:
        async with session.begin():
            user = User(
                phone=phone,
                nickname="用户{}".format(phone[-4:]),
                status=UserStatus.ACTIVE,
                role=UserRole.USER,
                provider_id=None,
            )
            session.add(user)
            await session.flush()
            row = LoginUserRow(
                id=user.id,
                nickname=user.nickname,
                phone=user.phone,
                role=user.role,
                provider_id=user.provider_id,
                status=user.status,
            )
    except IntegrityError as exc:
        if not _is_phone_unique_violation(exc):
            raise
        # 并发首次登录：别人刚把这条手机号建好了
        await session.rollback()
        existing = await _find_by_phone(session, phone)
        if existing is None:
            # 还是没找到：不是并发建号的问题，原样抛出
            raise
        return existing
    return row


def _is_phone_unique_violation(exc: IntegrityError) -> bool:
    """判断这个完整性冲突是不是 phone 唯一约束（uq_user_phone）撞了。

    只认这一种冲突：别的冲突（主键、外键、CHECK）重试没有意义，
    静默重读会把真正的错误藏起来。
    """
    orig = getattr(exc, "orig", None)
    constraint = getattr(orig, "constraint_name", None)
    if constraint is None:
        # 驱动没给约束名时从消息里兜底解析
        match = _CONSTRAINT_PATTERN.search(str(exc))
        constraint = match.group(1) if match else None
    return constraint == USER_PHONE_CONSTRAINT
