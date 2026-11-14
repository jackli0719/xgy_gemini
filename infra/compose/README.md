# infra/compose

Docker Compose 编排文件（开发与生产环境），由后续任务卡引入。

## 服务

| 服务 | 作用 | 默认是否启动 |
|---|---|---|
| `postgres` | PostgreSQL 16，开发与测试共用实例 | 是 |
| `redis` | Redis 7 | 是 |
| `api-test` | 只跑 pytest 的测试容器 | 否（`profiles: ["test"]`） |

## 常用命令

```bash
make up        # 起 postgres + redis（不会拉起 api-test）
make test      # 在 api-test 容器里跑全部测试（单元 + 集成）
make test-unit # 只跑单元测试
make down      # 清理
```

## 约定

- **`api-test` 不对外暴露端口**，只在 compose 网络内访问 postgres（主机名是服务名 `postgres`，不是 `localhost`）。
- **测试用独立数据库**：集成 fixture 每次会 `drop_all` + `create_all`，所以 `TEST_DATABASE_URL` 指向 `${POSTGRES_DB}_test`，绝不指向开发库 `${POSTGRES_DB}`。
- **集成测试不许静默 skip**：容器里设了 `REQUIRE_INTEGRATION=1`，只要有集成测试被 skip（或一个都没收集到），pytest 就判失败。守卫逻辑在 `apps/api/tests/conftest.py`。
- **插值读根目录 `.env`**：Makefile 里用 `docker compose --env-file .env`，compose 的 `${...}` 才会取到 `.env` 的真实值。不加的话会退回默认的 `oto/oto/oto`，与 `.env` 里 `DATABASE_URL` 的密码对不上。
- **`POSTGRES_PORT`**：宿主机映射端口可改（本机 5432 常被别的 postgres 占用）。只影响宿主机端口，容器内仍是 5432。
