"""服务商作用域的共享事实。

这里只放**多个 service 都要用、而且必须保持一致**的东西：

1. 「这个师傅不在本商」的统一文案（``MASTER_NOT_FOUND_DETAIL``）；
2. 服务商侧角色 -> 审计操作方类型的映射（``operator_type_for_provider_role``）。

为什么单独一个模块：派单（app.services.dispatch）和师傅管理
（app.services.master_management）要判断的是同一件事——「这个师傅是不是本商的」。
两处各写一份文案 / 映射，迟早漂移：漂了的后果是同一个错误在两个接口里
长得不一样（客户端没法用统一的方式处理），或者审计日志把操作方记成别人。

**这里只放事实，不放流程**：具体怎么改、怎么写日志，各 service 自己负责。
"""
from __future__ import annotations

from app.models.enums import OperatorType, UserRole

__all__ = [
    "MASTER_NOT_FOUND_DETAIL",
    "operator_type_for_provider_role",
]

# 「不存在」与「属于别家」共用的消息。
#
# 消息里只回客户端自己给的 id，不含任何归属信息（属于谁、什么状态），
# 所以「别家的师傅」和「根本不存在的师傅」在响应里完全一样，
# 攻击者无法据此判断某个师傅 id 是否真实存在（R1）。
MASTER_NOT_FOUND_DETAIL = "师傅不存在：master_id={master_id}"

# 服务商侧角色 -> 审计日志里的操作方类型。
#
# 两套枚举的取值在这一段是对齐的（见 app/models/enums.py）。
# 审计日志必须记**真实操作人**：管理员记 PROVIDER_ADMIN、员工记 PROVIDER_STAFF，
# 写死成 PROVIDER_ADMIN 等于把员工的操作记在管理员头上，追溯时指错人。
_OPERATOR_TYPE_BY_ROLE: dict[UserRole, OperatorType] = {
    UserRole.PROVIDER_ADMIN: OperatorType.PROVIDER_ADMIN,
    UserRole.PROVIDER_STAFF: OperatorType.PROVIDER_STAFF,
}


def operator_type_for_provider_role(role: UserRole) -> OperatorType | None:
    """服务商侧角色 -> 审计操作方类型；不是服务商侧角色返回 None。

    返回 None 而不是抛异常：抛哪种异常属于各条链路的语义（派单抛
    DispatchForbiddenError，师傅管理抛自己的），由调用方决定。
    """
    return _OPERATOR_TYPE_BY_ROLE.get(role)
