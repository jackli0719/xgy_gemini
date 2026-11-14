"""审计日志表。

记录金额 / 佣金等关键字段的变更，供 R3 规则「非授权角色可触发金额变更」追溯。

设计约束：
- 不可变：只追加，不更新，不设 updated_at。
- 不设物理外键：审计记录必须能保留「对象已被删除」的历史变更，
  因此用 target_type + target_id 做软关联。
"""
from sqlalchemy import BigInteger, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin
from app.models.enums import OperatorType, pg_enum


class AuditLog(Base, CreatedAtMixin):
    """审计日志。"""

    __tablename__ = "audit_log"
    __table_args__ = (
        # 服务商侧按「服务商 + 时间」检索审计记录
        Index("ix_audit_log_provider_created", "provider_id", "created_at"),
        # 按被审计对象检索（软关联，不建外键）
        Index("ix_audit_log_target", "target_type", "target_id"),
        # 按操作方检索
        Index("ix_audit_log_operator", "operator_type", "operator_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    operator_type: Mapped[OperatorType] = mapped_column(
        # operator_type 枚举已在 order_status_log.operator_type 创建，本列复用不重复建类型
        pg_enum(OperatorType, "operator_type", create_type=False),
        nullable=False,
    )
    # 约定：operator_type=SYSTEM 时 operator_id 固定为 0（系统保留 ID），不使用 NULL
    operator_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # 被审计对象的类型与主键，如 'order' / 'service_provider' / 'settlement'
    target_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # 涉及服务商侧操作时填写，便于按服务商检索；平台侧操作为空
    provider_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # 发生变更的字段名，如 'amount' / 'commission_rate'
    field_name: Mapped[str] = mapped_column(String(64), nullable=False)
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
