"""用户表。"""
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin
from app.models.enums import UserRole, UserStatus, pg_enum

# 角色与服务商归属的一致性约束。
#
# 规则只有一条：服务商侧角色（PROVIDER_ADMIN / PROVIDER_STAFF）必须带 provider_id，
# 其余角色必须不带。这样「谁属于哪个服务商」在库里只有一种表达，
# 不需要靠 role 和 provider_id 两列的组合去猜。
#
# 这段 SQL 必须与迁移 0004_user_role_provider 里的原文**逐字一致**，
# 否则模型（测试用 create_all 建表）与迁移（生产用 alembic 建表）会长出两套约束。
# apps/api/tests/api/test_auth_model.py 里有一条测试专门比对这两处文本。
USER_ROLE_PROVIDER_CHECK_SQL = (
    "(role IN ('PROVIDER_ADMIN', 'PROVIDER_STAFF') AND provider_id IS NOT NULL) "
    "OR (role NOT IN ('PROVIDER_ADMIN', 'PROVIDER_STAFF') AND provider_id IS NULL)"
)


class User(Base, TimestampMixin):
    """C 端用户（下单主体），同时也是各类后台账号的登录账号。"""

    __tablename__ = "user"
    __table_args__ = (
        UniqueConstraint("phone", name="uq_user_phone"),
        # 服务商端按 provider_id 过滤自己的账号
        Index("ix_user_provider_id", "provider_id"),
        CheckConstraint(
            USER_ROLE_PROVIDER_CHECK_SQL,
            name="ck_user_role_provider",
        ),
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
    # 角色。默认是普通 C 端用户；后台账号按角色区分能做什么。
    role: Mapped[UserRole] = mapped_column(
        pg_enum(UserRole, "user_role"),
        nullable=False,
        default=UserRole.USER,
        server_default=UserRole.USER.value,
    )
    # 归属的服务商。只有服务商侧角色非空（由 ck_user_role_provider 保证）。
    provider_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("service_provider.id", ondelete="RESTRICT", name="fk_user_provider_id"),
        nullable=True,
    )
