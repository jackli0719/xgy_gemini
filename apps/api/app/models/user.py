"""用户表。"""
from sqlalchemy import BigInteger, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin
from app.models.enums import UserStatus, pg_enum


class User(Base, TimestampMixin):
    """C 端用户（下单主体）。"""

    __tablename__ = "user"
    __table_args__ = (
        UniqueConstraint("phone", name="uq_user_phone"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    phone: Mapped[str] = mapped_column(String(32), nullable=False)
    nickname: Mapped[str] = mapped_column(String(64), nullable=False, server_default="")
    status: Mapped[UserStatus] = mapped_column(
        pg_enum(UserStatus, "user_status"),
        nullable=False,
        default=UserStatus.ACTIVE,
        server_default=UserStatus.ACTIVE.value,
    )
