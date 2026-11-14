"""结算单表与结算明细表。

一张结算单 = 某个服务商在一段时间内的一批完工订单的汇总：

- ``settlement``：汇总行（金额三件套、结算周期、状态）；
- ``settlement_item``：明细行，一行一笔订单（UNIQUE(order_id)）。

**金额口径**（三者必须自洽）：

- ``total_amount``：周期内订单金额之和（客户实付）；
- ``commission_amount``：平台佣金 = total_amount × 服务商佣金率；
- ``net_amount``：服务商实收 = total_amount - commission_amount。

``commission_rate`` 存在 service_provider 表上（0~1），是**平台**抽成的比例，
所以 net 是「扣掉平台佣金之后服务商拿到的钱」。口径写在这里，
service（app/services/settle.py）与迁移里的 CHECK 约束都跟着它走。
"""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin
from app.models.enums import SettlementStatus, pg_enum


class Settlement(Base, TimestampMixin):
    """结算单（服务商维度、按周期汇总）。"""

    __tablename__ = "settlement"
    __table_args__ = (
        # 同一服务商的同一结算周期只能有一张结算单
        UniqueConstraint(
            "provider_id",
            "period_start",
            "period_end",
            name="uq_settlement_provider_period",
        ),
        # 服务商侧按「服务商 + 状态」查自己的结算单
        Index("ix_settlement_provider_status", "provider_id", "status"),
        CheckConstraint("total_amount >= 0", name="ck_settlement_total_amount"),
        CheckConstraint(
            "commission_amount >= 0", name="ck_settlement_commission_amount"
        ),
        CheckConstraint("net_amount >= 0", name="ck_settlement_net_amount"),
        CheckConstraint(
            "period_start <= period_end", name="ck_settlement_period_range"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # 结算单的归属服务商。RESTRICT：服务商不能被物理删除——
    # 结算记录是钱的凭据，删掉等于销毁账目。
    provider_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("service_provider.id", ondelete="RESTRICT"),
        nullable=False,
    )
    # 结算周期（左闭右闭的日期区间）
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    # 客户实付合计
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    # 平台佣金
    commission_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    # 服务商实收
    net_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    status: Mapped[SettlementStatus] = mapped_column(
        # settlement_status 类型由本模型首次引用时创建（create_type=True）；
        # 迁移侧显式 CREATE TYPE，用 create_type=False（见 alembic/versions/0005_settlement.py）
        pg_enum(SettlementStatus, "settlement_status"),
        nullable=False,
        default=SettlementStatus.PENDING,
        server_default=SettlementStatus.PENDING.value,
    )
    # 确认人 / 确认时间：还没有确认时都是空
    confirmed_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class SettlementItem(Base):
    """结算明细：一笔订单对应一行。"""

    __tablename__ = "settlement_item"
    __table_args__ = (
        # 一笔订单只能出现在一张结算单的明细里：
        # 这是「重复结算」的兜底约束——不管哪条路径重复处理了同一笔订单，
        # 数据库都会挡住。
        UniqueConstraint("order_id", name="uq_settlement_item_order_id"),
        Index("ix_settlement_item_settlement_id", "settlement_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # 所属结算单。结算单删掉，明细跟着删（CASCADE）。
    settlement_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("settlement.id", ondelete="CASCADE"),
        nullable=False,
    )
    # 被结算的订单。RESTRICT：订单不能被物理删除——
    # 订单是钱的来源依据，结算单引用它就不许消失。
    order_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("order.id", ondelete="RESTRICT"),
        nullable=False,
    )
    # 该订单计入结算的金额（等于订单金额）
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
