.PHONY: help up down logs ps test test-unit

COMPOSE_FILE := infra/compose/docker-compose.dev.yml
# --env-file .env：让 compose 的 ${...} 插值读根目录 .env。
# 不加的话 compose 会退回默认值（oto/oto/oto），与 .env 里 DATABASE_URL 写的密码对不上。
COMPOSE := docker compose --env-file .env -f $(COMPOSE_FILE)

help: ## 显示可用目标
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-6s\033[0m %s\n", $$1, $$2}'

up: ## 启动本地开发容器（postgres + redis）
	@test -f .env || { echo "缺少 .env，请先执行 cp .env.example .env 并填写必填项"; exit 1; }
	$(COMPOSE) up -d

down: ## 停止并移除本地开发容器
	$(COMPOSE) down

logs: ## 跟踪查看容器日志
	$(COMPOSE) logs -f

ps: ## 查看容器运行状态
	$(COMPOSE) ps

test: ## 在容器里跑全部测试（单元 + 集成；集成测试必须真的跑，不许静默 skip）
	@test -f .env || { echo "缺少 .env，请先执行 cp .env.example .env 并填写必填项"; exit 1; }
	$(COMPOSE) --profile test run --rm api-test

test-unit: ## 只跑单元测试（集成测试会被过滤掉，输出里会打印跳过了几个）
	@test -f .env || { echo "缺少 .env，请先执行 cp .env.example .env 并填写必填项"; exit 1; }
	$(COMPOSE) --profile test run --rm api-test pytest -m "not integration"
