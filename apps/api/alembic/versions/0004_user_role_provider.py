"""给 user 表加角色与服务商归属

Revision ID: 0004_user_role_provider
Revises: 0003_order_slot_id
Create Date: 2026-11-14

背景：T-09 派单需要知道「当前操作者属于哪个服务商」，这个 provider_id
必须来自可信来源（JWT），而 JWT 里的角色和归属最终要落到 user 表上——
没有这两列，服务商侧的身份就只能从请求体里取，那是 R1 数据隔离的破口。

设计：

- role 是 PG 枚举 user_role，NOT NULL，server_default 'USER'。
  默认按普通 C 端用户对待：老数据不需要回填，也不会有「没配角色的账号
  意外拿到权限」的空窗。
- provider_id 是 bigint 可空外键 -> service_provider(id) ON DELETE RESTRICT。
  删服务商时不允许级联删账号——账号是登录身份，物理删掉等于丢失审计线索。
- ck_user_role_provider 把「角色」和「服务商归属」绑在一起：
  服务商侧角色（PROVIDER_ADMIN / PROVIDER_STAFF）必须有 provider_id，
  其余角色必须没有。这样「谁属于哪个服务商」在库里只有一种表达。

注意 MASTER（师傅）：师傅的归属权威来源是 master 表，不是 user.provider_id。
师傅账号在 user 表里的 role 是 MASTER、provider_id 必须为空——
它的服务商归属由 master.provider_id 决定。两者的一致性目前没有模型层校验（技术债）。
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_user_role_provider"
down_revision: str | None = "0003_order_slot_id"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# 枚举取值。顺序不影响语义，但保持与 app/models/enums.py 的 UserRole 一致。
USER_ROLE = (
    "USER",
    "MASTER",
    "PROVIDER_ADMIN",
    "PROVIDER_STAFF",
    "PLATFORM_ADMIN",
    "PLATFORM_OPS",
    "PLATFORM_FINANCE",
    "PLATFORM_CS",
)

# 枚举类型由本迁移显式创建，加列时一律 create_type=False，避免重复 CREATE TYPE
user_role = postgresql.ENUM(*USER_ROLE, name="user_role", create_type=False)

# 角色与服务商归属的一致性约束。
# 必须与 app/models/user.py 的 USER_ROLE_PROVIDER_CHECK_SQL **逐字一致**：
# 模型是测试库建表的依据，迁移是生产库建表的依据，两边文本不同就等于两套规则。
ROLE_PROVIDER_CHECK_SQL = (
    "(role IN ('PROVIDER_ADMIN', 'PROVIDER_STAFF') AND provider_id IS NOT NULL) "
    "OR (role NOT IN ('PROVIDER_ADMIN', 'PROVIDER_STAFF') AND provider_id IS NULL)"
)


def upgrade() -> None:
    op.execute(
        "CREATE TYPE user_role AS ENUM ({})".format(
            ", ".join("'{}'".format(v) for v in USER_ROLE)
        )
    )

    op.add_column(
        "user",
        sa.Column(
            "role",
            user_role,
            nullable=False,
            server_default=sa.text("'USER'"),
        ),
    )
    op.add_column(
        "user",
        sa.Column("provider_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_user_provider_id",
        "user",
        "service_provider",
        ["provider_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_user_role_provider",
        "user",
        ROLE_PROVIDER_CHECK_SQL,
    )
    op.create_index("ix_user_provider_id", "user", ["provider_id"])


def downgrade() -> None:
    op.drop_index("ix_user_provider_id", table_name="user")
    op.drop_constraint("ck_user_role_provider", "user", type_="check")
    op.drop_constraint("fk_user_provider_id", "user", type_="foreignkey")
    op.drop_column("user", "provider_id")
    op.drop_column("user", "role")
    op.execute("DROP TYPE IF EXISTS user_role")
