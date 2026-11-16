"""鉴权依赖：从 Authorization 头解 JWT，拿到当前用户。

边界（有意收窄）：

- **只验签解 claim，不查库**。用户是否存在、是否被禁用，留给后续卡片。
  这里一旦查库，鉴权就绑上了数据库可用性，失败路径也会变复杂。
- **任何失败都返回同一个 401 Unauthorized**，消息不区分原因
  （缺 header / 格式错 / 验签失败 / 过期）。
  区分开就等于给攻击者一个 oracle：他能靠报错差异判断某个 token
  是不是「有效但过期」，从而试探签发逻辑。

JWT 里带什么：

- ``sub``：用户 ID；
- ``role``：角色（app.models.enums.UserRole 的取值）；
- ``provider_id``：归属的服务商，只有服务商侧角色非空。

角色和 provider_id 都**只从签名过的 token 里取**，绝不从请求体、查询参数
或 header 里取——那些都是客户端可控的，拿它们做租户隔离等于没有隔离（R1）。
provider_id 与 role 的一致性由数据库 CHECK 约束 ck_user_role_provider 保证
（见 app/models/user.py），签发侧不重复校验。

JWT 库用 PyJWT（见 requirements.txt）：HS256 只需要标准库 hmac，
不必拉 cryptography 轮子；解码时显式钉住 ``algorithms=[...]``，
杜绝算法混淆。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

import jwt
from fastapi import Depends, Header, HTTPException, status

from app.core.config import settings
from app.core.timezone import now_utc
from app.models.enums import UserRole

__all__ = [
    "CurrentUser",
    "create_access_token",
    "get_current_user",
    "is_provider_role",
    "is_valid_role_provider_pair",
    "require_master_scope",
    "require_platform_admin",
    "require_platform_finance",
    "require_platform_settlement_viewer",
    "require_platform_staff",
    "require_provider_scope",
]

# 所有鉴权失败共用这一条消息，不区分原因
UNAUTHORIZED_DETAIL = "Unauthorized"

# 所有越权失败共用这一条消息，不区分是「角色不对」还是「provider_id 缺失」。
# 区分开就等于泄露了服务端的状态：攻击者能靠报错差异反推某个账号的归属，
# 甚至区分出「这是个服务商账号」（只是没带归属）还是「这是个普通用户」。
FORBIDDEN_DETAIL = "Forbidden"

# 服务商侧角色：只有这两种角色带 provider_id，也只有这两种角色能进服务商作用域。
PROVIDER_ROLES = frozenset({UserRole.PROVIDER_ADMIN, UserRole.PROVIDER_STAFF})

# 平台侧「运营」角色：PLATFORM_ADMIN 与 PLATFORM_OPS。
#
# 这两种角色能进平台侧的**只读总览**（订单总览）与**目录管理**（品类 / 服务项）。
# 它们与服务商侧一样不带 provider_id（数据库 CHECK 约束强制），
# 所以在平台上看到的不是「某一家的数据」，而是全平台的数据。
PLATFORM_STAFF_ROLES = frozenset({UserRole.PLATFORM_ADMIN, UserRole.PLATFORM_OPS})

# 平台侧「结算可见」角色：PLATFORM_FINANCE 与 PLATFORM_ADMIN。
#
# **看**和**确认**是两件事，卡在这两个角色之间：
# - 平台管理员管全局（服务商入驻、订单总览），看一眼结算单列表
#   是合理的（对账、核查服务商）；
# - 但「确认结算」是把钱定下来的动作，只归财务
#   （见 app.services.settle._require_finance_role）。
#
# 所以列表接口放这两个角色，确认接口只放 PLATFORM_FINANCE。
PLATFORM_SETTLEMENT_VIEW_ROLES = frozenset(
    {UserRole.PLATFORM_FINANCE, UserRole.PLATFORM_ADMIN}
)

# 缺少 header 时同样要 401。
# 这里用 Header(default=None) 而不是 Header(...):
# 后者会被 FastAPI 当成「必填参数缺失」返回 422，
# 而鉴权失败语义上应该是 401。缺 header 由我们自己判断并抛 401。


@dataclass(frozen=True)
class CurrentUser:
    """当前登录用户的轻量身份。

    身份三件套：用户 ID、角色、归属的服务商。
    三者都来自已验签的 token，不查库。
    """

    user_id: int
    role: UserRole
    provider_id: int | None


def is_valid_role_provider_pair(role: UserRole, provider_id: int | None) -> bool:
    """角色与 provider_id 的组合是否自洽。

    这是数据库 CHECK 约束 ck_user_role_provider 的**纯函数镜像**：
    服务商侧角色必须带 provider_id，其余角色必须不带。

    为什么不直接查库判断：鉴权路径每请求都要走一次，不能为此多一次往返；
    更重要的是，这个函数和数据库约束必须表达同一条规则，
    所以它的行为由 apps/api/tests/api/test_auth_model.py 盯着，
    并且那条测试还比对了模型里的约束文本与迁移里的原文是否逐字一致。
    """
    if role in PROVIDER_ROLES:
        return provider_id is not None
    return provider_id is None


def is_provider_role(role: UserRole) -> bool:
    """是否是服务商侧角色。"""
    return role in PROVIDER_ROLES


def create_access_token(
    user_id: int,
    role: UserRole | str,
    provider_id: int | None,
    *,
    expires_delta: timedelta | None = None,
) -> str:
    """签发访问令牌（HS256）。

    给测试和后续的登录接口用。``expires_delta`` 传负数即可造过期 token。

    role / provider_id 是必填参数（没有默认值）：签发方必须显式说清楚
    「这个账号是什么角色、属于哪个服务商」。给个隐式默认值等于让调用方
    在没想清楚的情况下签出一个角色错配的 token。
    """
    resolved_role = _coerce_role(role)
    now = now_utc()
    if expires_delta is None:
        expires_delta = timedelta(minutes=settings.jwt_access_expire_minutes)
    payload = {
        "sub": str(user_id),
        "role": resolved_role.value,
        "provider_id": provider_id,
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

    刻意不查库：role 和 provider_id 直接来自 token。
    代价是「账号已被禁用/服务商已被停用」不会立刻生效，
    收益是鉴权不依赖数据库可用性。这笔账后面用 token 短有效期来补。
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
            # role 是必填 claim：旧版 token（没有 role）直接判 401，
            # 不做「缺 role 就当普通用户」的兼容——那等于给旧 token 开后门
            options={"require": ["exp", "sub", "role"]},
        )
    except jwt.PyJWTError:
        # 验签失败 / 过期 / 载荷格式错 / 缺 claim，全在这里收敛
        raise _unauthorized() from None

    user_id = _parse_user_id(payload.get("sub"))
    if user_id is None:
        raise _unauthorized()
    role = _parse_role(payload.get("role"))
    if role is None:
        raise _unauthorized()
    provider_id, provider_ok = _parse_provider_id(payload.get("provider_id"))
    if not provider_ok:
        raise _unauthorized()
    return CurrentUser(user_id=user_id, role=role, provider_id=provider_id)


async def require_provider_scope(
    current: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    """FastAPI 依赖：要求当前用户处于某个服务商的作用域内。

    通过条件：角色是 PROVIDER_ADMIN / PROVIDER_STAFF，且 provider_id 非空。
    不满足 -> 403 Forbidden，消息不区分失败原因。

    满足时返回 current，后面的 router 直接取 ``current.provider_id``
    做租户过滤——不用再从请求参数里问「你要处理哪个服务商的订单」。
    """
    if not is_provider_role(current.role) or current.provider_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=FORBIDDEN_DETAIL,
        )
    return current


async def require_master_scope(
    current: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    """FastAPI 依赖：要求当前用户是师傅（MASTER 角色）。

    通过条件：角色是 MASTER。不满足 -> 403 Forbidden，消息不区分失败原因
    （与服务商侧的 require_provider_scope 同一句话）。

    注意这里只判**角色**，不判「这个账号有没有师傅身份」：
    那是 service 层按 master 表查出来的（见 app.services.master_queries），
    依赖层不查库——鉴权路径不该绑上数据库可用性。
    """
    if current.role is not UserRole.MASTER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=FORBIDDEN_DETAIL,
        )
    return current


async def require_platform_admin(
    current: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    """FastAPI 依赖：要求当前用户是平台管理员（PLATFORM_ADMIN 角色）。

    通过条件：角色是 PLATFORM_ADMIN。不满足 -> 403 Forbidden，
    消息与别处的越权失败一致（不区分「角色不对」还是「没带归属」）。

    平台侧角色按数据库约束（ck_user_role_provider）**不带 provider_id**：
    平台管理员不属于任何一家服务商，租户隔离对它没有意义。
    """
    if current.role is not UserRole.PLATFORM_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=FORBIDDEN_DETAIL,
        )
    return current


async def require_platform_staff(
    current: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    """FastAPI 依赖：要求当前用户是平台侧运营角色（PLATFORM_ADMIN / PLATFORM_OPS）。

    通过条件：角色在这两个平台侧角色里。不满足 -> 403 Forbidden，
    消息与别处的越权失败一致（不区分「角色不对」还是「没带归属」）。

    与 ``require_platform_admin`` 的区别：那一道只放 PLATFORM_ADMIN
    （服务商入驻 / 冻结是管理动作）；这一道多放一个 PLATFORM_OPS
    （平台运营：看订单总览、管品类与服务项）。

    这两个角色都**不带 provider_id**（数据库 CHECK 约束强制），
    所以它们看到的是全平台的数据——这是平台侧的特权，不是越权：
    边界在「角色」上，不在「归属」上。
    """
    if current.role not in PLATFORM_STAFF_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=FORBIDDEN_DETAIL,
        )
    return current


async def require_platform_finance(
    current: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    """FastAPI 依赖：要求当前用户是平台财务（PLATFORM_FINANCE 角色）。

    通过条件：角色是 PLATFORM_FINANCE。不满足 -> 403 Forbidden，
    消息与别处的越权失败一致（不区分「角色不对」还是「没带归属」）。

    **为什么单独一道门**：钱相关的**写**动作（确认结算）只有财务能做，
    与「平台运营」（看订单总览、管目录）不是一回事——运营看得见单子，
    但不能替财务确认结算单。

    注意这一道只管**写**：「看」结算单列表管理员也能看，
    走的是 ``require_platform_settlement_viewer``。

    失败发生在**碰库之前**：角色不对的账号连「有几张待结算单」都问不到。
    """
    if current.role is not UserRole.PLATFORM_FINANCE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=FORBIDDEN_DETAIL,
        )
    return current


async def require_platform_settlement_viewer(
    current: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    """FastAPI 依赖：要求当前用户能**看**平台结算单列表。

    通过条件：角色是 PLATFORM_FINANCE 或 PLATFORM_ADMIN。
    不满足 -> 403 Forbidden，消息与别处的越权失败一致。

    与 ``require_platform_finance`` 的区别：那一道只放财务，
    用于**确认结算**这类写钱的动作；这一道放行「看」——
    平台管理员要能对账、核查服务商的结算情况。

    失败同样发生在**碰库之前**：角色不对的账号连「有几张待结算单」
    都问不到。
    """
    if current.role not in PLATFORM_SETTLEMENT_VIEW_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=FORBIDDEN_DETAIL,
        )
    return current


def _coerce_role(role: UserRole | str) -> UserRole:
    """把角色参数归一成 UserRole；不是合法取值就抛 ValueError。"""
    if isinstance(role, UserRole):
        return role
    return UserRole(role)


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


def _parse_role(value: object) -> UserRole | None:
    """把 ``role`` 载荷解析成 UserRole；不是合法取值就返回 None。"""
    if not isinstance(value, str):
        return None
    try:
        return UserRole(value)
    except ValueError:
        return None


def _parse_provider_id(value: object) -> tuple[int | None, bool]:
    """把 ``provider_id`` 载荷解析成服务商 ID。

    返回 (provider_id, 是否合法)。合法 = None（无归属）或正整数；
    布尔、字符串、零、负数一律不合法。
    """
    if value is None:
        return None, True
    if isinstance(value, bool) or not isinstance(value, int):
        return None, False
    return (value, True) if value > 0 else (None, False)


def _unauthorized() -> HTTPException:
    """构造统一的 401。"""
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=UNAUTHORIZED_DETAIL,
    )
