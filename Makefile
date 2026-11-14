.PHONY: help up down logs ps test test-unit

COMPOSE_FILE := infra/compose/docker-compose.dev.yml
COMPOSE_PORTS_FILE := infra/compose/docker-compose.dev.ports.yml
# --env-file .env：让 compose 的 ${...} 插值读根目录 .env。
# 不加的话 compose 会退回默认值（oto/oto/oto），与 .env 里 DATABASE_URL 写的密码对不上。
COMPOSE := docker compose --env-file .env -f $(COMPOSE_FILE)
# 开发栈：叠加端口覆盖层，postgres / redis 会发布到宿主机，开发者可直连。
COMPOSE_DEV := $(COMPOSE) -f $(COMPOSE_PORTS_FILE)

help: ## 显示可用目标
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-6s\033[0m %s\n", $$1, $$2}'

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
