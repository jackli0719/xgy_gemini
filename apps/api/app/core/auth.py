"""鉴权依赖：从 Authorization 头解 JWT，拿到当前用户。

边界（有意收窄）：

- **只验签解 claim，不查库**。用户是否存在、是否被禁用，留给后续卡片。
  这里一旦查库，鉴权就绑上了数据库可用性，失败路径也会变复杂。
- **不做 RBAC、不做角色、不做服务商隔离**。当前只解决「这是谁」。
- **任何失败都返回同一个 401 Unauthorized**，消息不区分原因
  （缺 header / 格式错 / 验签失败 / 过期）。
  区分开就等于给攻击者一个 oracle：他能靠报错差异判断某个 token
  是不是「有效但过期」，从而试探签发逻辑。

JWT 库用 PyJWT（见 requirements.txt）：HS256 只需要标准库 hmac，
不必拉 cryptography 轮子；解码时显式钉住 ``algorithms=[...]``，
杜绝算法混淆。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Header, HTTPException, status

from app.core.config import settings

__all__ = ["CurrentUser", "create_access_token", "get_current_user"]

# 所有鉴权失败共用这一条消息，不区分原因
UNAUTHORIZED_DETAIL = "Unauthorized"

# 缺少 header 时同样要 401。
# 这里用 Header(default=None) 而不是 Header(...):
# 后者会被 FastAPI 当成「必填参数缺失」返回 422，
# 而鉴权失败语义上应该是 401。缺 header 由我们自己判断并抛 401。


@dataclass(frozen=True)
class CurrentUser:
    """当前登录用户的轻量身份。

    只带 user_id。角色 / 权限 / 服务商归属等留到后续卡片再加——
    现在加等于提前固化一个还没定下来的授权模型。
    """

    user_id: int


def create_access_token(
    user_id: int,
    *,
    expires_delta: timedelta | None = None,
) -> str:
    """签发访问令牌（HS256）。

    给测试和后续的登录接口用。``expires_delta`` 传负数即可造过期 token。
    """
    now = datetime.now(timezone.utc)
    if expires_delta is None:
        expires_delta = timedelta(minutes=settings.jwt_access_expire_minutes)
    payload = {
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int((now + expires_delta).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_alg)


async def get_current_user(
    authorization: str | None = Header(default=None),
) -> CurrentUser:
    """FastAPI 依赖：解析 Authorization 头，返回当前用户。

    任何失败（缺 header / 不是 Bearer / token 非法 / 签名不对 / 已过期 /
    载荷缺字段）都抛 401 Unauthorized，消息一致。
    """
    token = _extract_bearer_token(authorization)
    if token is None:
        raise _unauthorized()

    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            # 显式钉住算法：不接受 token 自己声明的 alg，
            # 否则会出现算法混淆（拿公钥当 HMAC 密钥用）那类攻击
            algorithms=[settings.jwt_alg],
            options={"require": ["exp", "sub"]},
        )
    except jwt.PyJWTError:
        # 验签失败 / 过期 / 载荷格式错 / 缺 claim，全在这里收敛
        raise _unauthorized() from None

    user_id = _parse_user_id(payload.get("sub"))
    if user_id is None:
        raise _unauthorized()
    return CurrentUser(user_id=user_id)


def _extract_bearer_token(authorization: str | None) -> str | None:
    """从 ``Authorization`` 头里取出 token；格式不对返回 None。

    scheme 大小写不敏感（RFC 7235），token 本身区分大小写。
    """
    if not authorization:
        return None
    parts = authorization.split(None, 1)
    if len(parts) != 2:
        return None
    scheme, token = parts
    if scheme.lower() != "bearer":
        return None
    token = token.strip()
    return token or None


def _parse_user_id(subject: object) -> int | None:
    """把 ``sub`` 载荷解析成用户 ID；不是正整数就返回 None。"""
    if isinstance(subject, bool):
        return None
    try:
        user_id = int(subject)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return user_id if user_id > 0 else None


def _unauthorized() -> HTTPException:
    """构造统一的 401。"""
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=UNAUTHORIZED_DETAIL,
    )
