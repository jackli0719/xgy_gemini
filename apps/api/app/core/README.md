# apps/api/app/core

核心基础设施：配置加载与数据库引擎。

- `config.py`：pydantic-settings 读取仓库根目录 `.env`。
- `database.py`：异步引擎与会话工厂。

鉴权、租户隔离（provider_id）与异常处理待后续任务卡引入。
