# OTO 项目状态（交接文档）

> 一页快照：给下一个接手的人看。**每张卡合并时同步更新本文件**（见「协作规则」）。
> 最后更新：2026-11-18

## 架构

- **Monorepo**：后端 Python + 前端 npm workspaces，共一个仓库、一个 CI。
- **`apps/api`**：FastAPI + SQLAlchemy 2.0 async + Alembic。一套 API（`/api/v1`）四端共用；
  分层为 `api → services → domain/models`，条件 UPDATE 认领 + 状态机 + 审计日志是全仓统一写法。
- **前端三端**：`apps/h5-user`（用户）、`apps/h5-master`（师傅）、`apps/web-admin`（平台端与服务商端**共用**一套后台，靠 `provider_id` 租户隔离，`provider_id` 由服务端从登录态推导）。
- **`packages/shared`**：openapi 生成的 TS SDK + 前后端共用的时区契约 JSON；`packages/ui`、`packages/config` 目前只是空骨架。
- **存储**：PostgreSQL 16（timestamptz）+ Redis 7（`infra/compose`）。业务日期口径与存库 UTC 口径分离，见「技术债」。
- **异常树**：每条业务链路一棵（PlaceOrder / Dispatch / MasterAction / MasterQuery / ServiceFlow / Settlement / Catalog / PlatformProvider / PlatformCatalog / MasterOnboarding），HTTP 状态码映射集中在 `app/api/v1/errors.py`。
- **测试**：后端单元 + 集成（集成用独立 `TEST_DATABASE_URL`，每次 drop_all + create_all，不走 alembic）；
  前端三端 vitest；`apps/api/tests/e2e` 是 API 级四端闭环；`e2e/` 是人工点一遍的三件套（seed / serve / clean）。

## 已完成

- 工程底座：monorepo 骨架、compose 编排、Makefile、CI 门禁 + 分支保护操作手册、`.env.example`。
- 数据与领域：全量模型 + 8 个 alembic 迁移、订单状态机、定价、时段规则、订单号生成。
- 后端 API：登录鉴权、地址、服务目录、下单、支付（mock 回调）、派单、师傅接单/开工/完工、
  服务商侧师傅管理、平台侧服务商管理与品类管理与订单总览、结算单生成（T+1）与财务确认、
  **师傅自助入驻（登记 → 平台审核）**。
- 前端三端：用户登录/地址/服务/下单；师傅待接单/开工完工；**师傅入驻申请页（选服务商 → 审核中 / 已入职分流）**；后台派单、师傅管理、服务商管理、订单总览、品类管理、结算确认、**平台侧师傅入驻审核页（通过可改判服务商 / 驳回必填理由）**。
- **用户下单路径的打磨（UI-01）**：品类列表 / 品类详情 / 下单页 / 订单列表四个页面统一了空状态（引导文案 + 按钮）、loading（骨架屏）、错误（网络错提示重试、业务错显示后端原话）；下单按钮提交中禁用，连点两次只发一次请求。
- **用户确认完成的路径打磨（UI-02）**：订单详情的「确认完成」按钮同步 ref 防连点（连点两次只发一次请求）、请求中按钮禁用、确认成功即变 COMPLETED 并显示完成时间、确认失败显示后端原话 + 重试按钮（不白屏）；状态已变（409/404）时提示并刷新最新状态；订单列表里 PENDING_CONFIRM 的行有醒目提示。
- **订单详情的完成时间（UI-02b）**：用户端与师傅端的订单详情响应都带 `completed_at`（未完成是 null），前端直接读详情接口的这个字段——打开一个**早已完成**的订单也能看到完成时间。
- **服务商派单路径的打磨（UI-03）**：后台派单页与师傅管理页统一了空状态（「暂无待派单订单」/「暂无师傅」+ 刷新按钮）；派单弹窗没有在岗师傅时提示「暂无在岗师傅」并禁用确认按钮；派单提交中按钮禁用、连点两次只发一次请求（同步 ref 守着）；派单失败（409 已派走 / 404 师傅不存在）显示后端原话并刷新列表；师傅状态切换有 loading 与连点守卫。
- **师傅端订单列表的打磨（UI-M1）**：待接单 / 待服务 / 服务中三个分组各有自己的空状态（暂无待接单 / 暂无待服务 / 暂无服务中）；请求中显示骨架屏；出错显示后端原话 + 重试按钮（不白屏，也**不**同时显示空状态）；订单卡片补上地址与时间（后端列表接口新增 `address_region` / `address_detail`，契约与前端类型已重新生成）；每个分组各自记 loading / error，切换分组重新请求。
- **师傅端订单详情的打磨（UI-M2）**：拒单成功后**不刷新详情**（后端拒单会把订单退回待派单并清空承接师傅，详情必然 404），改成记一条一次性回执「已拒单」+ 跳回列表；四个动作按钮用同步 ref 防连点（不只靠 disabled）+ 请求中 loading；操作失败显示后端原话 + 「返回列表」，订单内容不白屏；按钮严格按状态给（其余状态一个都不给）。顺带按后端真实契约对齐了错误语义——**订单侧冲突一律 404**（不存在 / 不是我的 / 状态已变，后端同构），**409 = 师傅当前不可接单**（停用 / 休假 / 未审核，只出现在接单 / 开工 / 完工，拒单不查在岗状态），只有 404 才刷新详情拿真实状态。
- 质量：后端 952 个用例（集成 352 个真跑、0 skip）、前端三端 185 个用例（h5-master 54 / h5-user 55 / web-admin 76）、API 级四端闭环 E2E、变异测试。
- 时区：全仓统一 Asia/Shanghai，业务日期（今天/时段/阈值/结算周期）按业务时区算，存库仍是 UTC timestamptz。

## 未完成

- **真实支付**：目前只有 mock 回调，没有接任何支付渠道。
- **打款出款**：结算单生成与财务确认有了，钱怎么打给服务商没做。
- **入驻审核结果通知**：平台审完了，师傅端没有推送也没有轮询——师傅要自己刷新页面才知道「已通过 / 已驳回」。
- **浏览器级 E2E**：Playwright 方案（任务 #24–#27）未开工，只有 API 级闭环与人工工具。
- **packages/ui / packages/config**：空骨架，尚无共享组件与工程配置。
- **生产部署**：镜像构建与上线流程、secret 轮换、备份恢复、监控告警。
- **生产部署检查清单**：已写出最小版（`docs/PRODUCTION_CHECKLIST.md`，10 条 + 验证命令），镜像构建、备份恢复、监控告警这些还没写。

## 技术债

- `.env` 占位值**有运行时检测了**（DEPLOY-01）：非 dev 环境启动即拒 `REPLACE_WITH` / `CHANGE_ME` / `<user>` 这类占位值与默认短信码 123456，报错只点名变量不回显值；但 `REDIS_URL` / `POSTGRES_PASSWORD` 不在 `Settings` 里，**仍靠 `docs/PRODUCTION_CHECKLIST.md` 人工核对**。
- 测试库走 `create_all`、生产走 alembic：两条建库路径可能长出不同 schema，改完模型/迁移**两边都要验**。
- 集成测试数下限 `EXPECTED_INTEGRATION_TESTS` 要手工同步（`ci.yml` 与 `docker-compose.dev.yml` 两处），漏改会误报红。
- 模型与迁移之间没有自动化一致性测试，只有几条针对单个迁移的测试。
- 根 `README.md` 的「当前状态」段落过时（还写着 T-01b 骨架）。
- 业务时区当前是固定 +08:00（Asia/Shanghai 无夏令时），将来若支持带夏令时的地区，阈值/结算口径要重算。
- `web-admin` 一个前端同时承载平台端与服务商端两套角色，页面变多后需要拆分。
- 全局 `~/.claude/settings.json` 里 3 条 http hook 端口过期（与本仓库 CI 无关）。
- **h5-master 的测试偶发一条未捕获异常**（`ReferenceError: window is not defined`，来自 Vant `use-height` 的定时器在 jsdom 环境销毁之后才触发）：用例**全过**，但 vitest 会报「Errors 1」并以非零码退出 → CI 的 h5-master job 可能**随机变红**。在 `main` 上用 worktree 复现过，是既有 flake、与具体卡片无关；待另开一卡处理（要么让定时器在 teardown 前跑完，要么在测试里 stub 掉）。
- **师傅入驻的三处取舍**（T-13）：
  1. 驳回用**删行**表达（没有 `REJECTED` 状态）——枚举值删不掉，加一个要同时改 `create_all` 与 alembic 两条建库路径；「没通过审核 = 没入职」语义也更干净。
  2. 师傅被服务商停用（`DISABLED`）后**不能自助重新申请**——自助重提会绕过服务商的停用决定；离职后重新入职要走平台介入。
  3. 入驻申请**没有身份证 / 资质字段**（表结构没动，也就没有迁移）；合规资质要上，需要另开一卡加列 + 迁移。
- 师傅身份与登录账号的一致性：**角色在登记时就改成 `MASTER`**，审核状态由 `master.status` 单独表达；`user.provider_id` 对师傅恒空（数据库 CHECK 约束强制），归属只由 `master.provider_id` 说了算。
- 入驻申请页的**入口**靠两条路：登录后按角色分流（role=USER 落地申请页）+ 导航栏「申请入驻」链接（未入职 / 审核中才有）。
- **入驻审核页只有「待审核」一个视图**：不传 status 就是全部，但页面固定按 `PENDING` 过滤；已入职 / 已驳回的历史记录只能查接口。改判服务商时只能选**营业中**的服务商（后端就只让改判到可加入的）。

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

- 本分支：`main` —— 已与 `origin/main` 同步，工作区干净。
- `main` HEAD：`ee0785d feat(UI-M2): master order detail actions (#19)`
  （含 UI-01 / UI-02 / UI-02b / UI-03 / UI-M1 / UI-M2 / PERF-01）
- 下一张卡：**UI-M3 师傅端登录页与入驻申请页打磨**（师傅端还没打磨过的两个页面）。
  要点：登录页的短信验证码（倒计时 / 重发 / 错误提示）与提交防连点；入驻申请页的空状态、
  服务商下拉为空时的提示、提交中禁用与防连点、提交失败显示后端原话（不白屏）。
  （备选：**UI-A1 后台入驻审核页与结算确认页打磨**——这两页是后台端还没走 UI-01/03 那套
  空状态 / loading / 错误处理的地方。）

## CI 现状

- **触发**：PR 到 `main`、push 到 `main` 各跑一遍；同 ref 新提交取消旧跑批。
- **后端 job**：pytest 单元 + 集成分两轮跑；集成测试**不许静默 skip**；再单独数一遍收集到的集成用例数，低于 `EXPECTED_INTEGRATION_TESTS`（现 352）直接红。
- **前端 job**：三个 workspace 各自 typecheck / test / build，矩阵展开成 3 个检查。
- **最近结果**：PR #19（UI-M2 师傅端订单详情操作打磨）4 个检查全绿并已合并进 `main`；历史故意造红的验证 PR（#2）确实红过，门禁有效。
- **Secrets**：`DATABASE_URL` / `TEST_DATABASE_URL` / `REDIS_URL` / `JWT_SECRET` / `POSTGRES_PASSWORD` 已配；`LOGIN_SMS_CODE` 未配（CI 里 `APP_ENV=dev`，走占位码）。
- **分支保护**：已按 `.github/BRANCH_PROTECTION.md` 在 Settings 里配好（4 个 required status checks + 1 approval + 禁 bypass）。
- **审查不在 CI 里**：走本地 Claude Code 审查，CI 只有一个可配的 review gate。
