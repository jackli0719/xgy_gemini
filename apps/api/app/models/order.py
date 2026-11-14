"""订单表与订单状态流转日志表。

订单状态只能通过状态机函数流转，并同时写 order_status_log（见 T-05a 规则 R4）。
"""
from datetime import datetime
from decimal import Decimal
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, TimestampMixin
from app.models.enums import OrderStatus, OperatorType, PayStatus, pg_enum


class Order(Base, TimestampMixin):
    """订单。"""

    __tablename__ = "order"
    __table_args__ = (
        UniqueConstraint("order_no", name="uq_order_order_no"),
        # 服务商端按「服务商 + 状态」过滤订单
        Index("ix_order_provider_status", "provider_id", "status"),
        Index("ix_order_user_id", "user_id"),
        # 按预约时段查订单
        Index("ix_order_slot_id", "slot_id"),
        CheckConstraint("amount >= 0", name="ck_order_amount"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_no: Mapped[str] = mapped_column(String(32), nullable=False)
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("user.id", ondelete="RESTRICT"),
        nullable=False,
    )
    # 未派单前为空；派单后指向承接的服务商
    provider_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("service_provider.id", ondelete="RESTRICT"),
        nullable=True,
    )
    master_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("master.id", ondelete="RESTRICT"),
        nullable=True,
    )
    address_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("address.id", ondelete="RESTRICT"),
        nullable=False,
    )
    item_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("service_item.id", ondelete="RESTRICT"),
        nullable=False,
    )
    # 预约的时段库存。订单必须绑定到具体的一格时段，
    # (item_id, date, start_time) 无法唯一定位（同服务项一天多格）。
    slot_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("schedule_slot.id", ondelete="RESTRICT"),
        nullable=False,
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    status: Mapped[OrderStatus] = mapped_column(
        pg_enum(OrderStatus, "order_status"),
        nullable=False,
        default=OrderStatus.PENDING_PAY,
        server_default=OrderStatus.PENDING_PAY.value,
    )
    pay_status: Mapped[PayStatus] = mapped_column(
        pg_enum(PayStatus, "pay_status"),
        nullable=False,
        default=PayStatus.UNPAID,
        server_default=PayStatus.UNPAID.value,
    )
    # 超时未确认由系统自动确认
    auto_confirmed: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OrderStatusLog(Base, CreatedAtMixin):
    """订单状态流转日志（每次状态变更留痕）。"""

    __tablename__ = "order_status_log"
    __table_args__ = (
        Index("ix_order_status_log_order_id", "order_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("order.id", ondelete="CASCADE"),
        nullable=False,
    )
    # 建单时无前置状态
    from_status: Mapped[OrderStatus | None] = mapped_column(
        pg_enum(OrderStatus, "order_status", create_type=False),
        nullable=True,
    )
    to_status: Mapped[OrderStatus] = mapped_column(
        pg_enum(OrderStatus, "order_status", create_type=False),
        nullable=False,
    )
    operator_type: Mapped[OperatorType] = mapped_column(
        pg_enum(OperatorType, "operator_type"),
        nullable=False,
    )
    operator_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
