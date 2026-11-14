"""服务分类与服务项目表。"""
from decimal import Decimal
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin
from app.models.enums import CatalogStatus, pg_enum


class ServiceCategory(Base, CreatedAtMixin):
    """服务分类，支持自引用形成树（parent_id 为空即一级分类）。"""

    __tablename__ = "service_category"
    __table_args__ = (
        Index("ix_service_category_parent_id", "parent_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    parent_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("service_category.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[CatalogStatus] = mapped_column(
        pg_enum(CatalogStatus, "catalog_status"),
        nullable=False,
        default=CatalogStatus.ACTIVE,
        server_default=CatalogStatus.ACTIVE.value,
    )
    sort_order: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )


class ServiceItem(Base, CreatedAtMixin):
    """服务项目（可下单的具体服务与价格）。"""

    __tablename__ = "service_item"
    __table_args__ = (
        Index("ix_service_item_category_id", "category_id"),
        CheckConstraint("base_price >= 0", name="ck_service_item_base_price"),
        CheckConstraint("duration_min > 0", name="ck_service_item_duration_min"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    category_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("service_category.id", ondelete="RESTRICT"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    base_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    duration_min: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[CatalogStatus] = mapped_column(
        # catalog_status 枚举已在 service_category.status 创建，本列复用不重复建类型
        pg_enum(CatalogStatus, "catalog_status", create_type=False),
        nullable=False,
        default=CatalogStatus.ACTIVE,
        server_default=CatalogStatus.ACTIVE.value,
    )
