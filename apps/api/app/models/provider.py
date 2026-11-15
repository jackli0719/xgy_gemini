"""服务商表与师傅表。

师傅必须归属某个服务商：master.provider_id 为 NOT NULL 外键。
"""
from decimal import Decimal
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin
from app.models.enums import MasterStatus, ProviderStatus, pg_enum


class ServiceProvider(Base, TimestampMixin):
    """服务商（租户主体）。"""

    __tablename__ = "service_provider"
    __table_args__ = (
        CheckConstraint(
            "commission_rate >= 0 AND commission_rate <= 1",
            name="ck_service_provider_commission_rate",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    contact_phone: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[ProviderStatus] = mapped_column(
        pg_enum(ProviderStatus, "provider_status"),
        nullable=False,
        # 新建的服务商一律「待审核」：平台建完还要审核（审核通过才转 ACTIVE），
        # 默认值给成 ACTIVE 等于默认放行，审核这一步就没了。
        # 迁移 0007 同步改了库里的列默认值，两条建库路径必须一致。
        default=ProviderStatus.PENDING,
        server_default=ProviderStatus.PENDING.value,
    )
    # 佣金比例，0 ~ 1（不是金额，故不用 decimal(12,2)）
    commission_rate: Mapped[Decimal] = mapped_column(
        Numeric(5, 4),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
    )


class Master(Base, TimestampMixin):
    """师傅（服务提供方人员），必须挂在一个服务商下。"""

    __tablename__ = "master"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_master_user_id"),
        Index("ix_master_provider_id", "provider_id"),
        CheckConstraint(
            "rating IS NULL OR (rating >= 0 AND rating <= 5)",
            name="ck_master_rating",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # 师傅归属：非空外键，服务商端按此列做租户隔离
    provider_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("service_provider.id", ondelete="RESTRICT"),
        nullable=False,
    )
    # 一个登录用户最多对应一个师傅身份
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("user.id", ondelete="RESTRICT"),
        nullable=False,
    )
    real_name: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[MasterStatus] = mapped_column(
        pg_enum(MasterStatus, "master_status"),
        nullable=False,
        default=MasterStatus.PENDING,
        server_default=MasterStatus.PENDING.value,
    )
    rating: Mapped[Decimal | None] = mapped_column(Numeric(2, 1), nullable=True)
