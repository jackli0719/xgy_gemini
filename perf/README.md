# 压测（PERF-01）

k6 压测基建：**独立压测库 + 种子数据 + 两组脚本**。

## 隔离边界

这张卡的核心约束是「压测不碰开发库和测试库」，靠三道闸保证：

| 闸 | 位置 | 作用 |
| --- | --- | --- |
| 独立容器 | `perf/compose.yaml` | `oto-perf-postgres` / `oto-perf-redis` / `oto-perf-api` 自成一套，不在 `oto-dev` 网络里，与开发栈零共享 |
| 独立库名 | 同上，`POSTGRES_DB=oto_perf` | 压测库是 `oto_perf`，开发库是 `oto`，测试库是 `oto_test` |
| 代码硬闸 | `perf/seed.py`、`perf/check_oversell.py` | 库名不以 `_perf` 结尾就**拒绝执行**，误用在开发栈里不会把开发数据清掉 |

端口也错开：压测 postgres 走宿主机 `54322`，api 走 `8101`（本机 5432 / 8000 被别的项目占着也不影响）。

## 组成

```
perf/
  compose.yaml      压测栈：postgres(oto_perf) + redis + api + k6
  seed.py           种子脚本（跑在 api 容器里，用应用自己的 ORM 与模型）
  check_oversell.py 超卖检查（查库比对 used / capacity / 订单数）
  k6/
    common.js       公共件：登录、下单、指标
    summary.js      汇总输出（P50/P95/P99 + 错误率）
    race.js         并发组：N 个 VU 抢同一格时段库存
    load.js         基线组：单接口（POST /api/v1/orders）QPS
  manifest.json     种子生成的「种子 ↔ k6」契约（不入库）
  out/              压测结果（summary json，不入库）
```

**k6 不需要本地安装**：跑压测的容器就是 `grafana/k6` 官方镜像。

## 命令

```bash
make perf-up      # 起 postgres + redis + api，并用迁移把 schema 建到 oto_perf
make perf-seed    # 往压测库种数据（写 manifest.json）
make perf-run     # 完整一轮：重新种数据 → 竞态 → 查库 → 基线 → 查库
make perf-race    # 只跑竞态组（要求时段库存是干净的，先 make perf-seed）
make perf-load    # 只跑基线组
make perf-check   # 只查库核对超卖
make perf-down    # 拆栈（连数据卷一起删）
```

常用环境变量：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `PERF_API_WORKERS` | 4 | api 的 uvicorn worker 数 |
| `PERF_DB_POOL_SIZE` | 20 | 每个 worker 的连接池大小 |
| `PERF_CUSTOMERS` | 600 | 压测客户数（每人 1 个地址） |
| `PERF_SLOTS_PER_ITEM` | 100 | 每个服务项的时段数 |
| `PERF_SLOT_CAPACITY` | 5 | 每格时段的容量（竞态组抢的就是这个数） |
| `VUS` | 竞态 100 / 基线 500 | 并发用户数 |
| `RATE` / `DURATION` | 不设 | 基线组改成恒定到达率模式（如 `RATE=50 DURATION=60s`） |

## 种子内容

1 个服务商（ACTIVE）· 1 个服务商管理员 · 5 个师傅（ACTIVE）· 1 个品类 · 10 个服务项 ·
每项 100 个时段（10 天 x 10 格，每格容量 5）· 600 个压测客户（各带 1 个地址）。

种子是**幂等**的：每次先 `TRUNCATE ... RESTART IDENTITY CASCADE` 再重种，
所以 id 稳定从 1 开始，`manifest.json` 里可以直接写死 id 供 k6 使用。

`manifest.json` 里有三样东西：

- `race`：竞态时段（item_id / slot_id / 容量）；
- `load_slots`：负载池（999 格，**不含**竞态时段，两组压测互不干扰）；
- `customers`：手机号与地址 id。

## 指标口径

- **P50 / P95 / P99**：只统计**下单接口**（`order_duration` 这个自定义 Trend）。
  不用 k6 自带的 `http_req_duration`，那会把 setup 阶段的 100~500 次登录也算进去，
  把下单的分位数稀释掉。
- **错误率**：`http_req_failed` 的 rate。竞态组里 409 是**预期结果**（没抢到），
  所以请求带了 `responseCallback: http.expectedStatuses(201, 409)`，
  409 不计入错误率；5xx 才会让这个数不为 0。
- **超卖**：k6 只看得见「谁抢到了」，看不见库存计数有没有写坏，
  所以另有一个 `perf/check_oversell.py` 查库收口，三条口径：
  1. `used > capacity` —— 直接超卖；
  2. `used != 该时段订单数` —— 库存计数与实际订单对不上；
  3. 竞态时段上 `订单数 != capacity` —— 抢到最后必须正好占满。

## 实测（本机 16 核 Mac，Docker Desktop；api 4 worker）

三轮 `make perf-run`，全部阈值通过：

**竞态组：100 VU 抢 5 格库存**

| 轮次 | 成功 201 | 冲突 409 | 5xx | P50 | P95 | P99 | 错误率 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | **5** | 95 | 0 | 641 ms | 732 ms | 736 ms | 0.00% |
| 2 | **5** | 95 | 0 | 331 ms | 426 ms | 430 ms | 0.00% |
| 3 | **5** | 95 | 0 | 336 ms | 443 ms | 455 ms | 0.00% |

每轮查库都是 `capacity=5 used=5 该时段订单数=5`，**无超卖**；
全库 1000 格时段扫描也没有 `used > capacity` 或「库存与订单对不上」的格子。

**基线组：500 VU 同时下单**

| 轮次 | 成功 201 | 5xx | P50 | P95 | P99 | 错误率 | 吞吐 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 500/500 | 0 | 1019 ms | 1438 ms | 1492 ms | 0.00% | 470 req/s |
| 2 | 500/500 | 0 | 1009 ms | 1534 ms | 1546 ms | 0.00% | 444 req/s |
| 3 | 500/500 | 0 | 1144 ms | 1751 ms | 1777 ms | 0.00% | 358 req/s |

## 踩过的坑（都写在配置注释里了）

- **单 worker 是单核瓶颈**：api 只跑 1 个 worker 时，进程 CPU 100% 打满，
  吞吐卡在 ~220 req/s，500 并发下单的 P95 是 **3.1s**（超过 2s 的目标）。
  改成 4 worker 后吞吐到 ~450 req/s、P95 落到 1.4~1.8s。
  worker 数更多（6 / 8）反而更慢 —— 连接与 CPU 竞争 outweigh 收益。
- **不是文件系统瓶颈**：把 postgres 数据目录换成 tmpfs、或关掉
  `synchronous_commit`，P95 都在同一区间（1.5~1.9s），说明瓶颈在
  「这台机器同时跑 k6 + api + postgres」的总量上，不是 WAL fsync。
  所以配置保持默认语义，不为了跑过阈值去改持久化行为。
- **竞态组必须重新种数据**：时段库存是种子种出来的，重复跑竞态组会撞上
  「库存已被上一轮吃掉」的 409，阈值会直接判失败——这是想要的行为，
  不能把上轮的结果当本轮的结果。`make perf-run` 已经先跑一遍 `perf-seed`。

## 压测库连接方式

```bash
postgresql+asyncpg://oto:oto@localhost:54322/oto_perf
```
