#!/usr/bin/env bash
#
# 人工测试：同时起三端前端（E2E-02）。
#
#   用户端 H5     http://localhost:5173   (apps/h5-user)
#   服务商后台    http://localhost:5174   (apps/web-admin)
#   师傅端 H5     http://localhost:5175   (apps/h5-master)
#
# 三个端口是硬约定：E2E 用例按端口区分三端，人工测试也一样，
# 一眼就能知道哪个窗口是哪个端。
#
# 端口被别的程序占了（比如本机还跑着别的项目）时，可以用环境变量改：
#
#   H5_USER_PORT=5183 H5_MASTER_PORT=5185 make e2e-serve
#
# 后端（FastAPI）**假定已经在跑**：
#
#   cd apps/api && uvicorn app.main:app --port 8000
#
# （`make up` 只起 postgres / redis，不起 API —— compose 里没有 api 服务。）
# 三端的前端都把 /api 代理到 http://localhost:8000（见各端 vite.config.ts），
# 所以后端没起的话接口会失败，脚本开头会提醒一句。
#
# Ctrl+C 三个一起停。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

API_TARGET="${VITE_API_PROXY_TARGET:-http://localhost:8000}"

USER_PORT="${H5_USER_PORT:-5173}"
ADMIN_PORT="${WEB_ADMIN_PORT:-5174}"
MASTER_PORT="${H5_MASTER_PORT:-5175}"

# ---- 后端在不在 ------------------------------------------------------
# 用 /docs 探活（FastAPI 自带的接口，不用猜业务路由）
if ! curl -s -o /dev/null --max-time 2 "${API_TARGET}/docs"; then
  echo "[serve] 提醒：后端 ${API_TARGET} 没响应，前端调接口会失败。"
  echo "[serve]        启动后端：cd apps/api && uvicorn app.main:app --port 8000"
fi

pids=()
labels=()
ports=()

# 递归杀进程树。
#
# `npm run dev` 是一条命令三层进程（npm -> sh -> vite），
# 只 kill 最外层那个 npm，vite 会留下来继续占着端口——
# 下次再跑就撞端口了。所以先杀子进程再杀自己。
kill_tree() {
  local pid="$1"
  local child
  for child in $(pgrep -P "$pid" 2>/dev/null || true); do
    kill_tree "$child"
  done
  kill "$pid" 2>/dev/null || true
}

cleanup() {
  trap - INT TERM EXIT
  for pid in "${pids[@]}"; do
    kill_tree "$pid"
  done
  wait 2>/dev/null || true
}
trap cleanup INT TERM EXIT

start() {
  local workspace="$1"
  local port="$2"
  local label="$3"
  # --strictPort：端口被占就直接报错退出，不要静默挪到下一个端口
  # （挪了就跟文档里的端口对不上了）
  npm run dev --workspace "$workspace" -- --port "${port}" --strictPort &
  pids+=("$!")
  labels+=("${label}")
  ports+=("${port}")
  echo "[serve] ${label} -> http://localhost:${port}"
}

start @oto/h5-user "${USER_PORT}" "用户端 H5"
start @oto/web-admin "${ADMIN_PORT}" "服务商后台"
start @oto/h5-master "${MASTER_PORT}" "师傅端 H5"

# ---- 起没起来 ------------------------------------------------------
# vite 启动要一两秒，等一下再逐个探活。
#
# 探活有两个条件，缺一不可：
#   1. 我们起的那个进程还活着（vite 撞端口会直接退出）
#   2. 端口有响应
# 只看第 2 条会误判：本机别的程序占着同一个端口时，curl 也通，
# 但通的不是我们这个前端。
sleep 3
failed=0
for i in "${!pids[@]}"; do
  label="${labels[$i]}"
  port="${ports[$i]}"
  if ! kill -0 "${pids[$i]}" 2>/dev/null; then
    echo "[serve] ${label} 启动失败：进程已经退出（多半是端口 ${port} 被占）。"
    echo "[serve]        换个端口重跑，例如："
    echo "[serve]        H5_USER_PORT=5183 WEB_ADMIN_PORT=5184 H5_MASTER_PORT=5185 make e2e-serve"
    failed=1
  elif curl -s -o /dev/null --max-time 2 "http://localhost:${port}/"; then
    echo "[serve] ${label} 已就绪（http://localhost:${port}）"
  else
    echo "[serve] ${label} 没起来：端口 ${port} 没响应。"
    echo "[serve]        多半是端口被占了。换个端口重跑，例如："
    echo "[serve]        H5_USER_PORT=5183 WEB_ADMIN_PORT=5184 H5_MASTER_PORT=5185 make e2e-serve"
    failed=1
  fi
done

if [ "$failed" -ne 0 ]; then
  exit 1
fi

echo "[serve] 三个都起来了，Ctrl+C 一起停。"
wait || true
