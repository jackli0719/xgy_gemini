# apps/api

FastAPI 后端服务，承载用户端、师傅端、平台端、服务商端共用的 REST API。

当前状态（T-07a）：仅有数据层 —— ORM 模型与 Alembic 迁移，尚无路由 / 服务 / Schema。

```
apps/api/
├─ app/
│  ├─ core/       配置（读根目录 .env）与异步数据库引擎
│  └─ models/     SQLAlchemy ORM 模型（10 张表）
└─ alembic/       迁移脚本，版本 0001_initial、0002_schedule_slot
```

安装依赖：`pip install -r requirements.txt`
应用迁移：在本目录执行 `alembic upgrade head`（需仓库根目录已有 `.env`）。
