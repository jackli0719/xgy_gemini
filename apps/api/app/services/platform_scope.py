"""平台侧（平台管理员 / 平台运营）共享的事实。

这里只放**多个 service 都要用、而且必须保持一致**的东西：

1. 平台侧角色 -> 审计操作方类型的映射（``operator_type_for_platform_role``）。

为什么单独一个模块：目录管理（app.services.platform_catalog）写审计日志时
要记**真实操作人**——平台管理员与平台运营在 R3「谁改的价」里是两拨人，
写死成 PLATFORM_ADMIN 等于把运营的操作记在管理员头上，追溯时指错人。

与服务商侧的同类映射（app.services.provider_scope.operator_type_for_provider_role）
是同一件事的两个方向，分开放是为了让两边各自的文案与映射互不干扰。

**这里只放事实，不放流程**：具体怎么改、怎么写日志，各 service 自己负责。
"""
from __future__ import annotations

from app.models.enums import OperatorType, UserRole

__all__ = [
    "operator_type_for_platform_role",
]

# 平台侧角色 -> 审计日志里的操作方类型。
#
# 两套枚举的取值在这一段是对齐的（见 app/models/enums.py）。
_OPERATOR_TYPE_BY_ROLE: dict[UserRole, OperatorType] = {
    UserRole.PLATFORM_ADMIN: OperatorType.PLATFORM_ADMIN,
    UserRole.PLATFORM_OPS: OperatorType.PLATFORM_OPS,
}


def operator_type_for_platform_role(role: UserRole) -> OperatorType | None:
    """平台侧角色 -> 审计操作方类型；不是平台侧角色返回 None。

    返回 None 而不是抛异常：抛哪种异常属于各条链路的语义，
    由调用方决定（目录管理抛 PlatformCatalogForbiddenError）。
    """
    return _OPERATOR_TYPE_BY_ROLE.get(role)
