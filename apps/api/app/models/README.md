# apps/api/app/models

SQLAlchemy ORM 模型（SQLAlchemy 2.0 声明式风格）。

- `base.py`：`Base` 与 `CreatedAtMixin` / `TimestampMixin`。
- `enums.py`：受控枚举取值（PostgreSQL 原生枚举类型）。
- `user.py` / `provider.py` / `catalog.py` / `address.py` / `order.py` / `audit_log.py` / `schedule_slot.py`：10 张表的模型定义。

改表结构后需在 `apps/api` 下执行 `alembic revision --autogenerate` 生成迁移。
