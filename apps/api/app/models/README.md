# apps/api/app/models

SQLAlchemy ORM 模型（SQLAlchemy 2.0 声明式风格）。

- `base.py`：`Base` 与 `CreatedAtMixin` / `TimestampMixin`。
- `enums.py`：受控枚举取值（PostgreSQL 原生枚举类型）。
- `user.py` / `provider.py` / `catalog.py` / `address.py` / `order.py` / `audit_log.py` / `schedule_slot.py`：10 张表的模型定义。

改表结构后需在 `apps/api` 下执行 `alembic revision --autogenerate` 生成迁移。

## flush 顺序约定

- **模型层不声明 ORM relationship**：async 下访问未加载的关联属性会触发 lazy load，直接抛 `MissingGreenlet` / `InvalidRequestError`。需要跨表数据时显式 `select` 标量列，不靠 relationship 导航。
- **mapper 排序按字母序，不按外键依赖**：SQLAlchemy 2.x 在没有 relationship 声明时，按 `模块名.类名` 的字母序（`Mapper._sort_key`）排序 mapper，**不解析外键依赖顺序**。
- **一次 flush 写多张有 FK 关联的表会违例**：外键所在表若在字母序上排在被引用表之后，插入时直接触发 FK 违例。必须逐个 flush（先写被引用表，flush 拿到主键后再写引用表），或改用 Core `insert` 显式控制顺序。
- **正例**：`app/services/place_order.py` 中 `order` 与 `order_status_log` 显式分两次 flush——先 flush `order` 拿到 `order.id`，再写状态流转日志。
- **反例**：同一次 flush 里写 `address` 与 `user`——字母序 `address` 在 `user` 之前，`address.user_id` 指向尚未插入的 `user.id`，直接 FK 违例。
- **后续 service 卡（派单、支付、退款等）必须遵守本节**，代码审查时逐条检查。
