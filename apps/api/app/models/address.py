"""用户收货地址表。"""
from sqlalchemy import BigInteger, Boolean, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin


class Address(Base, CreatedAtMixin):
    """收货地址。"""

    __tablename__ = "address"
    __table_args__ = (
        Index("ix_address_user_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
    )
    contact: Mapped[str] = mapped_column(String(64), nullable=False)
    phone: Mapped[str] = mapped_column(String(32), nullable=False)
    region: Mapped[str] = mapped_column(String(255), nullable=False)
    detail: Mapped[str] = mapped_column(String(512), nullable=False)
    is_default: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
