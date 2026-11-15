.PHONY: help up down logs ps test test-unit test-file openapi h5-test h5-build h5-typecheck master-h5-test master-h5-build master-h5-typecheck web-test web-build web-typecheck

COMPOSE_FILE := infra/compose/docker-compose.dev.yml
COMPOSE_PORTS_FILE := infra/compose/docker-compose.dev.ports.yml
# --env-file .env：让 compose 的 ${...} 插值读根目录 .env。
# 不加的话 compose 会退回默认值（oto/oto/oto），与 .env 里 DATABASE_URL 写的密码对不上。
COMPOSE := docker compose --env-file .env -f $(COMPOSE_FILE)
# 开发栈：叠加端口覆盖层，postgres / redis 会发布到宿主机，开发者可直连。
COMPOSE_DEV := $(COMPOSE) -f $(COMPOSE_PORTS_FILE)

help: ## 显示可用目标
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-9s\033[0m %s\n", $$1, $$2}'

up: ## 启动本地开发容器（postgres + redis，发布宿主机端口供直连）
	@test -f .env || { echo "缺少 .env，请先执行 cp .env.example .env 并填写必填项"; exit 1; }
	$(COMPOSE_DEV) up -d

down: ## 停止并移除本地开发容器
	$(COMPOSE_DEV) down

logs: ## 跟踪查看容器日志
	$(COMPOSE_DEV) logs -f

ps: ## 查看容器运行状态
	$(COMPOSE_DEV) ps

# 测试用哪套 compose 文件（调用参数 = 传给 pytest 的额外参数）：
#   - 开发栈正在跑，且它的 postgres 已经发布了宿主机端口映射
#     -> 用 COMPOSE_DEV。这套配置和运行中的容器一致，compose 不会重建容器，
#        开发栈的宿主机端口映射也不会被一次测试收走（up / test 交替不互相破坏）。
#   - 否则（开发栈没起，或它的容器没发布端口）
#     -> 用 COMPOSE（基础层）。基础层不发布任何宿主机端口，
#        所以宿主机 5432/6379 被别的容器占着也能直接跑测试。
define run_tests
	@cid=$$($(COMPOSE_DEV) ps -q postgres 2>/dev/null); \
	nb=$$(docker inspect -f '{{len .HostConfig.PortBindings}}' "$$cid" 2>/dev/null || true); \
	if [ -n "$$cid" ] && [ -n "$$nb" ] && [ "$$nb" -gt 0 ]; then \
		echo "[make] 复用已运行的开发栈：postgres 已发布宿主机端口，容器不会被重建"; \
		$(COMPOSE_DEV) --profile test run --rm api-test $(1); \
	else \
		echo "[make] 开发栈未运行或未发布端口：用基础层启动 postgres+redis（不占用宿主机端口）"; \
		$(COMPOSE) --profile test run --rm api-test $(1); \
	fi
endef

test: ## 在容器里跑全部测试（单元 + 集成；集成测试必须真的跑，不许静默 skip）
	@test -f .env || { echo "缺少 .env，请先执行 cp .env.example .env 并填写必填项"; exit 1; }
	$(call run_tests,)

test-unit: ## 只跑单元测试（集成测试会被过滤掉，输出里会打印跳过了几个）
	@test -f .env || { echo "缺少 .env，请先执行 cp .env.example .env 并填写必填项"; exit 1; }
	$(call run_tests,pytest -m "not integration")

# 只跑指定文件：开发迭代时用，不跑全量。
# 守卫：指定了路径就算「部分运行」，「集成测试数下限」那条守卫不生效
# （见 apps/api/tests/conftest.py），但「集成测试不许静默 skip」仍然生效。
# 例：make test-file FILE=tests/services/test_auto_confirm.py
#     make test-file FILE=tests/api/test_orders.py PYTEST_ARGS="-k dispatch"
test-file: ## 只跑指定测试文件（例：make test-file FILE=tests/api/test_orders.py）
	@test -f .env || { echo "缺少 .env，请先执行 cp .env.example .env 并填写必填项"; exit 1; }
	@test -n "$(FILE)" || { echo "缺少 FILE 参数。例：make test-file FILE=tests/api/test_orders.py"; exit 1; }
	$(call run_tests,pytest $(FILE) $(PYTEST_ARGS))

# ---- 前端：用户端 H5 ----
# 独立工程（apps/h5-user），用 npm workspaces 里的脚本跑。
h5-test: ## 跑用户端 H5 的前端测试（vitest）
	npm run test --workspace @oto/h5-user

h5-build: ## 构建用户端 H5（产物在 apps/h5-user/dist）
	npm run build --workspace @oto/h5-user

h5-typecheck: ## 用户端 H5 类型检查（vue-tsc）
	npm run typecheck --workspace @oto/h5-user

# ---- 前端：师傅端 H5 ----
# 独立工程（apps/h5-master），用 npm workspaces 里的脚本跑。
master-h5-test: ## 跑师傅端 H5 的前端测试（vitest）
	npm run test --workspace @oto/h5-master

master-h5-build: ## 构建师傅端 H5（产物在 apps/h5-master/dist）
	npm run build --workspace @oto/h5-master

master-h5-typecheck: ## 师傅端 H5 类型检查（vue-tsc）
	npm run typecheck --workspace @oto/h5-master

# ---- 前端：服务商 Web 后台 ----
# 独立工程（apps/web-admin），同样用 npm workspaces 里的脚本跑。
web-test: ## 跑服务商 Web 后台的前端测试（vitest）
	npm run test --workspace @oto/web-admin

web-build: ## 构建服务商 Web 后台（产物在 apps/web-admin/dist）
	npm run build --workspace @oto/web-admin

web-typecheck: ## 服务商 Web 后台类型检查（vue-tsc）
	npm run typecheck --workspace @oto/web-admin

# 导出 OpenAPI 契约到 apps/api/openapi.json（前端据此生成类型）。
# 在容器里跑：跟测试同一个镜像环境，导出的 schema 与测试断言的 schema
# 一定是同一份（本地 Python 版本不一样时不会导出成另一套）。
# --no-deps：导契约不碰数据库，不用起 postgres / redis。
# 源码是挂载进容器的（见 compose 的 volumes），写出来的 openapi.json 直接落到宿主机。
openapi: ## 导出 OpenAPI 契约到 apps/api/openapi.json
	@test -f .env || { echo "缺少 .env，请先执行 cp .env.example .env 并填写必填项"; exit 1; }
	$(COMPOSE) --profile test run --rm --no-deps api-test python -m app.scripts.export_openapi
