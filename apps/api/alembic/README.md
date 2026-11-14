# apps/api/alembic

Alembic 数据库迁移脚本，版本化管理 schema 变更。

- `env.py` 从仓库根目录 `.env` 的 `DATABASE_URL` 取连接（异步 asyncpg 驱动）。
- `versions/` 存放迁移脚本，首个迁移为 `0001_initial`（9 张表 + 7 个枚举类型）。
- 常用命令（在 `apps/api` 目录下执行）：

```bash
alembic upgrade head                  # 应用迁移
alembic downgrade -1                  # 回滚一版
alembic revision --autogenerate -m "" # 模型变更后生成迁移
alembic check                         # 检查模型与数据库结构是否一致
```
