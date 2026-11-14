.PHONY: help up down logs ps

COMPOSE_FILE := infra/compose/docker-compose.dev.yml
COMPOSE := docker compose -f $(COMPOSE_FILE)

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
