"""ORM 模型集合。

Alembic 的 env.py 依赖本模块把全部模型注册进 Base.metadata。
"""
from app.models.address import Address
from app.models.audit_log import AuditLog
from app.models.base import Base, CreatedAtMixin, TimestampMixin
from app.models.catalog import ServiceCategory, ServiceItem
from app.models.enums import (
    CatalogStatus,
    MasterStatus,
    OperatorType,
    OrderStatus,
    PayStatus,
    ProviderStatus,
    UserRole,
    UserStatus,
)
from app.models.order import Order, OrderStatusLog
from app.models.provider import Master, ServiceProvider
from app.models.schedule_slot import ScheduleSlot
from app.models.user import User

__all__ = [
    "Address",
    "AuditLog",
    "Base",
    "CatalogStatus",
    "CreatedAtMixin",
    "Master",
    "MasterStatus",
    "OperatorType",
    "Order",
    "OrderStatus",
    "OrderStatusLog",
    "PayStatus",
    "ProviderStatus",
    "ScheduleSlot",
    "ServiceCategory",
    "ServiceItem",
    "ServiceProvider",
    "TimestampMixin",
    "User",
    "UserRole",
    "UserStatus",
]
