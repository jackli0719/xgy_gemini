# main 分支保护（Branch Protection）

> 这份文档是**给人看的操作手册**。仓库的分支保护设置**不会**由 CI 自动修改，
> 也不建议用脚本改——保护规则被悄悄改掉，比没有保护更危险。
> 下面的步骤照着点一遍即可，一次性的。

## 1. main 必须满足的条件

在仓库 **Settings → Branches → Branch protection rules → Add rule** 里，
给 `main` 加一条规则（也可以直接编辑已有的 main 规则）：

| 项 | 设成什么 | 为什么 |
| --- | --- | --- |
| Branch name pattern | `main` | 只保护主干 |
| Require a pull request before merging | ✅ 开启，**1** approvals | 改动必须有人看过 |
| Require approvals | 至少 1 个 approval | 至少一个人签字 |
| Dismiss stale approvals when new commits are pushed | ✅ 开启 | 推了新代码就重新让人看 |
| Do not allow bypassing the above settings | ✅ 开启 | 连管理员也不能跳过（要临时跳过得自己改设置） |
| Require status checks to pass before merging | ✅ 开启 | CI 必须全绿 |
| Required status checks | 见下面第 2 节 | 三个 job 都要绿 |
| Require conversation resolution before merging | ✅ 开启 | 评审里的问题必须先回复完 |
| Allow force pushes | ❌ 关掉 | 不许改写历史 |
| Allow deletions | ❌ 关掉 | 不许删分支 |
| Block linear history | 关掉（保持现状） | 本仓库用 squash merge 记录 PR |
| Automatically merge pull requests | 关掉 | 合并时机由人决定 |

### 明确禁止的两件事

- **禁止 force push**（`git push --force` / `--force-with-lease`）：会把别人已经拉到
  本地的历史改掉，历史一旦被改写就查不回来了。
- **禁止直接 push main**：所有改动走 PR。CI 的 push 触发器只是「合并之后再验一遍」，
  不是绕过 PR 的入口。

## 2. Required status checks（必过的检查）

CI（`.github/workflows/ci.yml`）有三个 job，**都要**勾成 required：

| 检查名（就是 job 的 `name`） | 说明 |
| --- | --- |
| `后端测试（pytest）` | 单元 + 集成，集成测试不许静默 skip |
| `前端测试（h5-user）` | 用户端 H5：typecheck / test / build |
| `前端测试（web-admin）` | 平台后台：typecheck / test / build |
| `前端测试（h5-master）` | 师傅端 H5：typecheck / test / build |
| `审查门禁（critical / high 阻断）` | 只在 pull_request 上跑；审查出 critical / high 就红 |

矩阵 job（前端）会展开成 3 个检查，**三个都要勾**——少勾一个，改那个包就能绕过去。

> `审查门禁` 只在 PR 事件上跑。GitHub 的 required check 是按「PR 头提交的这次运行」
> 算的，PR 事件一定会跑出这个检查，所以可以安全地设成 required。

## 3. 首次运行前要手动配置的 Secrets

CI 从 GitHub Secrets 读下面这些。**仓库设置 → Secrets and variables → Actions →
Repository secrets → New repository secret**。

| Secret | 必填 | 说明与生成方式 |
| --- | --- | --- |
| `JWT_SECRET` | ✅ | HS256 验签密钥，**至少 32 字节**，短了应用会拒绝启动。<br>`python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `POSTGRES_PASSWORD` | ✅ | CI 里 postgres 服务容器的密码。<br>`python -c "import secrets; print(secrets.token_urlsafe(16))"` |
| `DATABASE_URL` | ✅ | 后端应用库地址，**必须指向 CI 里的 postgres 服务容器**：<br>`postgresql+asyncpg://oto:<POSTGRES_PASSWORD>@localhost:5432/oto` |
| `TEST_DATABASE_URL` | ✅ | 集成测试库地址，**必须是另一个库**（集成 fixture 每次 drop_all + create_all，指向同一个库会把应用库清空）：<br>`postgresql+asyncpg://oto:<POSTGRES_PASSWORD>@localhost:5432/oto_test` |
| `REDIS_URL` | ✅ | `redis://localhost:6379/0` |
| `LOGIN_SMS_CODE` | | 短信验证码。CI 里 `APP_ENV=dev`，留空等于用占位码 `123456`；填了就用填的 |
| `GEMINI_API_KEY` | ✅ | 审查门禁用的模型 API key（`run-agy-sdk` 的 `api-key` 入参） |

两个 URL 里的密码必须和 `POSTGRES_PASSWORD` 一致——CI 的 postgres 容器是拿
`POSTGRES_PASSWORD` 起来的，URL 里的密码对不上就连不上库。

用户名与库名（`oto` / `oto`）**不用配成 Secret**：它们写在 workflow 的
`services.postgres.env` 里（连 healthcheck 也用同样的字面量），不是机密。
但 URL 里的库名必须跟它对上。

`.env.example` 里的其余必填项（`AUTO_CONFIRM_THRESHOLD_HOURS`、`JWT_ALG` 等）
在 CI 里都有默认值或用不到，不用配成 Secret。

## 4. 为什么这份文档是手动的

分支保护规则和 Secrets 都不是代码：

- 改保护规则会**立刻**影响所有人能不能合代码，脚本误改（比如把 required checks
  清空）会静悄悄地拆掉门禁，而且很难发现；
- Secrets 的值本来就只该存在于仓库设置里，不该进版本库，也不该由流水线自己写。

所以：**代码里的门禁（CI）由 PR 改，仓库里的门禁（分支保护）由人点一次。**
两者都要有——CI 全绿但没有分支保护，是可以绕过的；分支保护但没有 CI，
是「全绿」的假象。

## 5. fail-closed：审查输出坏掉时也阻断

审查门禁的判定逻辑（`.github/workflows/ci.yml` 的最后一步）：

- 代理输出能被解析成 JSON 数组，且里面**没有** `severity` 为 `critical` / `high`
  的条目 → 通过；
- 出现 `critical` / `high` → 失败（阻断合并），并把每条问题打印到日志里；
- **输出根本不是合法 JSON 数组**（代理挂了、被限流、输出被截断）→ 也失败。

最后一条是故意的：审查没跑成 ≠ 审查通过。宁可卡住让人看一眼，也不要让一次
「代理抽风」变成一次无声放行。要临时绕过，就按第 1 节临时关掉 required check
——那个动作是显式的、会留在设置变更记录里。

## 5.1 审查门禁只审高风险文件（提速）

门禁的**目标**是守住四条不变量：数据隔离（R1）、结算金额留痕（R3）、
状态机（R4）、权限提升（R5）。为此把整个 PR 的 diff 丢给审查代理既慢又吵——
前端、测试、文档的改动占了大头，却几乎不可能踩到这四条。

所以门禁**只审高风险文件**：

| 范围 | 路径 |
| --- | --- |
| 高风险（**必审**） | `apps/api/alembic/`、`apps/api/app/services/`、`apps/api/app/core/auth.py`、`apps/api/app/api/v1/`、`apps/api/app/models/` |
| 低风险（**跳过**） | 前端（`apps/web-admin`、`apps/h5-*`、`packages/`）、测试文件、文档（`*.md`）、`openapi.json`、`schema.ts` |

行为上有三条：

1. **prompt 里只有高风险文件的 diff**，审查代理看到的东西小得多；
2. **这次 PR 没碰任何高风险文件**时，门禁**不调用审查代理**直接通过
   （日志里会写「本次没有高风险改动」）——省掉一整轮模型调用；
3. job 的 `timeout-minutes` 是 **5**：跑不完就是 job 红 = 阻断合并
   （与第 5 节的 fail-closed 同一口径：没审成 ≠ 审过）。

> 已知取舍：`apps/api/app/schemas/`（请求体校验层）目前**不在**高风险白名单里，
> 改那里的金额/状态校验不会被门禁看到——要补的话改
> `.github/workflows/ci.yml` 里的 `HIGH_RISK_PATHS` 数组即可（加一行）。

**这不是降低标准，是把标准用在对的地方**：前端与测试由前两个 job 兜住
（typecheck / test / build 全绿），剩下的人力与机器时间全砸在可能出事故的
那几类文件上。

## 6. 一次典型的合并流程

```bash
git switch feature/xxx
git add -A && git commit -m "feat(xxx): ..."
git push -u origin feature/xxx
gh pr create --base main --fill
# 等 CI：后端 / 前端 ×3 / 审查门禁 五个检查全绿
# 评审人 approve + 把评审里的问题回复完
gh pr merge --squash
```

推完代码后想看 CI 跑得怎么样：

```bash
gh pr checks <PR号> --watch
```
