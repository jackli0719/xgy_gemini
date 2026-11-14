# infra/compose

Docker Compose 编排文件（开发与生产环境），由后续任务卡引入。

## 服务

| 服务 | 作用 | 默认是否启动 |
|---|---|---|
| `postgres` | PostgreSQL 16，开发与测试共用实例 | 是 |
| `redis` | Redis 7 | 是 |
| `api-test` | 只跑 pytest 的测试容器 | 否（`profiles: ["test"]`） |

## 编排文件

| 文件 | 作用 | 谁在用 |
|---|---|---|
| `docker-compose.dev.yml` | 基础层：postgres / redis / api-test。**不发布任何宿主机端口** | `make test` / `make test-unit` |
| `docker-compose.dev.ports.yml` | 覆盖层：只给 postgres / redis 加宿主机端口映射 | `make up` / `down` / `logs` / `ps` |

端口发布与否分两层，是为了让「跑测试」这件事完全不依赖宿主机端口：
宿主机 5432/6379 被别的容器占着时，`make test` 照样能直接跑。
基础层里并没有删掉端口配置——需要直连时叠加覆盖层即可。

## 常用命令

```bash
make up        # 起 postgres + redis（发布宿主机端口，不会拉起 api-test）
make test      # 在 api-test 容器里跑全部测试（单元 + 集成）
make test-unit # 只跑单元测试
make down      # 清理
```

**改了依赖（`apps/api/requirements*.txt`）必须先重建测试镜像**——
`make test` 用的 `docker compose run` 不会自动重建，镜像里没有新装的包时
会直接报 `ModuleNotFoundError`：

```bash
docker compose --env-file .env -f infra/compose/docker-compose.dev.yml \
  -f infra/compose/docker-compose.dev.ports.yml --profile test build api-test
```

## 约定

- **`api-test` 不对外暴露端口**，只在 compose 网络内访问 postgres（主机名是服务名 `postgres`，不是 `localhost`）。
- **测试用独立数据库**：集成 fixture 每次会 `drop_all` + `create_all`，所以 `TEST_DATABASE_URL` 指向 `${POSTGRES_DB}_test`，绝不指向开发库 `${POSTGRES_DB}`。
- **集成测试不许静默 skip**：容器里设了 `REQUIRE_INTEGRATION=1`，只要有集成测试被 skip（或一个都没收集到），pytest 就判失败。守卫逻辑在 `apps/api/tests/conftest.py`。
- **插值读根目录 `.env`**：Makefile 里用 `docker compose --env-file .env`，compose 的 `${...}` 才会取到 `.env` 的真实值。不加的话会退回默认的 `oto/oto/oto`，与 `.env` 里 `DATABASE_URL` 的密码对不上。
- **容器里读不到仓库根的 `.env`**：`app/core/config.py` 按文件路径上溯找 `.env`，容器里那个路径不存在，所以应用配置全靠环境变量注入。`api-test` 服务显式传了 `JWT_SECRET` / `JWT_ALG`（鉴权依赖 `app/core/auth.py` 验签要用），缺 `JWT_SECRET` 时 compose 直接报错，不会用空密钥把服务起起来。
- **`POSTGRES_PORT` / `REDIS_PORT`**：宿主机映射端口可改（本机 5432 / 6379 常被别的容器占用）。只影响宿主机端口，容器内仍是 5432 / 6379。这两项在 `make up` 时生效；`make test` 不发布端口，因此用不到。
- **`make test` 会自适应选 compose 文件**：
  - 开发栈正在跑、且它的 postgres 已经发布了宿主机端口 → 用叠加端口层的那套，配置与运行中的容器一致，
    compose 不会重建容器，开发栈的端口映射也不会被一次测试收走（`make up` / `make test` 交替执行互不破坏）。
  - 否则 → 只用基础层，postgres / redis 不占宿主机端口，宿主机端口被别的容器占着也能跑。

## 状态残留

`make test` 用的是 `docker compose run --rm`，测试容器跑完即删；postgres / redis 是常驻服务，由 `make down` 清理。
测试用的 `oto_test` 库与开发用的 `oto` 库在同一个实例里但互不影响——集成 fixture 只 drop 测试库。

