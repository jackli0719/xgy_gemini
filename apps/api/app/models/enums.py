"""受控枚举取值。

全部使用 PostgreSQL 原生枚举类型，取值集合由数据库强制约束。
新增取值需 `ALTER TYPE ... ADD VALUE`，不能靠应用层塞值。
"""
from enum import Enum

from sqlalchemy.dialects import postgresql


class UserStatus(str, Enum):
    """用户状态。"""

    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"
    BANNED = "BANNED"


class ProviderStatus(str, Enum):
    """服务商状态。"""

    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class MasterStatus(str, Enum):
    """师傅状态。"""

    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    ON_LEAVE = "ON_LEAVE"
    DISABLED = "DISABLED"


class CatalogStatus(str, Enum):
    """服务分类 / 服务项目状态。"""

    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class PayStatus(str, Enum):
    """订单支付状态。"""

    UNPAID = "UNPAID"
    PAID = "PAID"
    REFUNDING = "REFUNDING"
    REFUNDED = "REFUNDED"


class OrderStatus(str, Enum):
    """订单状态机取值（12 态，流转由状态机函数负责）。"""

    PENDING_PAY = "PENDING_PAY"
    PENDING_DISPATCH = "PENDING_DISPATCH"
    PENDING_ACCEPT = "PENDING_ACCEPT"
    ACCEPTED = "ACCEPTED"
    IN_SERVICE = "IN_SERVICE"
    PENDING_CONFIRM = "PENDING_CONFIRM"
    COMPLETED = "COMPLETED"
    PENDING_SETTLE = "PENDING_SETTLE"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"
    REFUNDING = "REFUNDING"
    REFUNDED = "REFUNDED"


class OperatorType(str, Enum):
    """订单状态流转的操作方类型。

    服务商侧区分管理员与普通员工，供 R3「非授权角色可触发金额变更」审计判定使用。
    """

    USER = "USER"
    MASTER = "MASTER"
    PROVIDER_ADMIN = "PROVIDER_ADMIN"
    PROVIDER_STAFF = "PROVIDER_STAFF"
    PLATFORM_ADMIN = "PLATFORM_ADMIN"
    SYSTEM = "SYSTEM"


def pg_enum(enum_cls: type[Enum], name: str, create_type: bool = True):
    """构造 PostgreSQL 原生枚举列类型。

    同一枚举类型被多列引用时，只有第一处 `create_type=True`，
    其余列传 False，避免重复 CREATE TYPE。
    """
    return postgresql.ENUM(enum_cls, name=name, create_type=create_type)
