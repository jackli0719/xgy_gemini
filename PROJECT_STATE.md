# OTO 项目状态（交接文档）

> 一页快照：给下一个接手的人看。**每张卡合并时同步更新本文件**（见「协作规则」）。
> 最后更新：2026-11-16

## 架构

- **Monorepo**：后端 Python + 前端 npm workspaces，共一个仓库、一个 CI。
- **`apps/api`**：FastAPI + SQLAlchemy 2.0 async + Alembic。一套 API（`/api/v1`）四端共用；
  分层为 `api → services → domain/models`，条件 UPDATE 认领 + 状态机 + 审计日志是全仓统一写法。
- **前端三端**：`apps/h5-user`（用户）、`apps/h5-master`（师傅）、`apps/web-admin`（平台端与服务商端**共用**一套后台，靠 `provider_id` 租户隔离，`provider_id` 由服务端从登录态推导）。
- **`packages/shared`**：openapi 生成的 TS SDK + 前后端共用的时区契约 JSON；`packages/ui`、`packages/config` 目前只是空骨架。
- **存储**：PostgreSQL 16（timestamptz）+ Redis 7（`infra/compose`）。业务日期口径与存库 UTC 口径分离，见「技术债」。
- **测试**：后端单元 + 集成（集成用独立 `TEST_DATABASE_URL`，每次 drop_all + create_all，不走 alembic）；
  前端三端 vitest；`apps/api/tests/e2e` 是 API 级四端闭环；`e2e/` 是人工点一遍的三件套（seed / serve / clean）。

## 已完成

- 工程底座：monorepo 骨架、compose 编排、Makefile、CI 门禁 + 分支保护操作手册、`.env.example`。
- 数据与领域：全量模型 + 8 个 alembic 迁移、订单状态机、定价、时段规则、订单号生成。
- 后端 API：登录鉴权、地址、服务目录、下单、支付（mock 回调）、派单、师傅接单/开工/完工、
  服务商侧师傅管理、平台侧服务商管理与品类管理与订单总览、结算单生成（T+1）与财务确认。
- 前端三端：用户登录/地址/服务/下单；师傅待接单/开工完工；后台派单、师傅管理、服务商管理、订单总览、品类管理、结算确认。
- 质量：后端 887 个用例（集成 303 个真跑、0 skip）、前端三端 92 个用例、API 级四端闭环 E2E、变异测试。
- 时区：全仓统一 Asia/Shanghai，业务日期（今天/时段/阈值/结算周期）按业务时区算，存库仍是 UTC timestamptz。

## 未完成

- **真实支付**：目前只有 mock 回调，没有接任何支付渠道。
- **打款出款**：结算单生成与财务确认有了，钱怎么打给服务商没做。
- **浏览器级 E2E**：Playwright 方案（任务 #24–#27）未开工，只有 API 级闭环与人工工具。
- **packages/ui / packages/config**：空骨架，尚无共享组件与工程配置。
- **生产部署**：镜像构建与上线流程、secret 轮换、备份恢复、监控告警。
- **生产部署检查清单**：`.env` 占位值的兜底文档还没写（见「技术债」）。

## 技术债

- `.env` 里 `REPLACE_WITH_*` 占位值**没有运行时检测**，靠「生产部署检查清单」文档卡兜底（该卡未写）。
- 测试库走 `create_all`、生产走 alembic：两条建库路径可能长出不同 schema，改完模型/迁移**两边都要验**。
- 集成测试数下限 `EXPECTED_INTEGRATION_TESTS` 要手工同步（`ci.yml` 与 `docker-compose.dev.yml` 两处），漏改会误报红。
- 模型与迁移之间没有自动化一致性测试，只有几条针对单个迁移的测试。
- 根 `README.md` 的「当前状态」段落过时（还写着 T-01b 骨架）。
- 业务时区当前是固定 +08:00（Asia/Shanghai 无夏令时），将来若支持带夏令时的地区，阈值/结算口径要重算。
- `web-admin` 一个前端同时承载平台端与服务商端两套角色，页面变多后需要拆分。
- 全局 `~/.claude/settings.json` 里 3 条 http hook 端口过期（与本仓库 CI 无关）。

## 协作规则

- 一卡一分支；特性分支不直接推 `main`，走 PR + squash；合并用 `--ff-only`。
- **禁止 `git reset --hard` 修合并错误**（用 `git revert` 或重新编排）；**禁止改写历史**；**禁止 force push**。
- **除非主控明确要求，不 push**；本卡只提交到本地分支。
- `.env` 与任何密钥（`.pem` / `.key` / secrets）**不入库**，只改 `.env.example`。
- **一条回复只做一个阶段**（提交+合并 / 下一张卡），做完用 `git log` 回传确认。
- **开发期只跑本次相关测试**（`make test-file FILE=...`），全量 `make test` 由主控在合并前跑。
- 每张卡做**变异测试**（改坏实现，确认测试真的红）并如实报告。
- **跑不了就说明卡在哪，不假装通过**。
- **每张卡合并时同步更新本文件**（架构 / 已完成 / 未完成 / 技术债 / 当前 commit / CI 现状）。

## 当前 commit

- 本分支：`feature/TZ-01-timezone` —— PR **#7 OPEN**，CI 全绿，**未合并**。
- 分支代码 HEAD：`09b12d9 fix(TZ-01): unify timezone to Asia/Shanghai`
- `main` HEAD：`0087dc6 feat(PLAT-03): platform settlement confirmation (#6)`
- 本文件自身的提交见 `git log -1`（`docs: project state handoff`）。

## CI 现状

- **触发**：PR 到 `main`、push 到 `main` 各跑一遍；同 ref 新提交取消旧跑批。
- **后端 job**：pytest 单元 + 集成分两轮跑；集成测试**不许静默 skip**；再单独数一遍收集到的集成用例数，低于 `EXPECTED_INTEGRATION_TESTS`（现 303）直接红。
- **前端 job**：三个 workspace 各自 typecheck / test / build，矩阵展开成 3 个检查。
- **最近结果**：PR #7 绿（2m40s）；`main` push #6 绿。历史故意造红的验证 PR（#2）确实红过，门禁有效。
- **Secrets**：`DATABASE_URL` / `TEST_DATABASE_URL` / `REDIS_URL` / `JWT_SECRET` / `POSTGRES_PASSWORD` 已配；`LOGIN_SMS_CODE` 未配（CI 里 `APP_ENV=dev`，走占位码）。
- **⚠️ `main` 目前实际没有分支保护**（GitHub API 报 `Branch not protected`）——操作手册在 `.github/BRANCH_PROTECTION.md`，需人工在 Settings 里勾选 4 个 required status checks + 1 approval + 禁 bypass。
- **审查不在 CI 里**：走本地 Claude Code 审查，CI 只有一个可配的 review gate。
