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
| Required status checks | 见下面第 2 节 | 四个检查都要绿 |
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

CI（`.github/workflows/ci.yml`）有两个 job，展开成**四个**检查，**都要**勾成 required：

| 检查名（就是 job 的 `name`） | 说明 |
| --- | --- |
| `后端测试（pytest）` | 单元 + 集成，集成测试不许静默 skip |
| `前端测试（h5-user）` | 用户端 H5：typecheck / test / build |
| `前端测试（web-admin）` | 平台后台：typecheck / test / build |
| `前端测试（h5-master）` | 师傅端 H5：typecheck / test / build |

矩阵 job（前端）会展开成 3 个检查，**三个都要勾**——少勾一个，改那个包就能绕过去。

> CI 里**没有**审查 job：审查走本地 Claude Code（见第 5 节），不在 GitHub runner 上跑。
> 少一个 required check 就等于少一道门禁——本仓库是 public 仓库，前端三个包与后端
> 一样都要盯住。

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

## 5. 审查：走本地，不进 CI

CI 里**没有**审查 job——审查由**本地 Claude Code** 在推代码之前做，
规则文件在仓库里：`code_review_agent/skills/code-review-and-quality/SKILL.md`。

| 项 | 说明 |
| --- | --- |
| 规则在哪 | `code_review_agent/skills/code-review-and-quality/SKILL.md`（随仓库进版本库） |
| 谁来跑 | 本地 Claude Code（人工发起，或主控在推之前主动跑一次） |
| 审什么 | 本次改动的 diff，只看高风险文件（见 5.1） |
| 判定 | `severity` 为 `critical` / `high` 的问题**必须改掉再推** |
| 兜底 | 分支保护要求 **1 个 approval**（第 1 节）——评审人签字是最后一道关 |

改成本地跑有三个理由：

1. **不消耗 CI 时间**：审查要调模型，跑在 runner 上就是每次 PR 都烧一次机器
   时间 + 一次模型调用，还经常超时拖慢整条流水线。
2. **仓库里不用放第三方 API key**：审查要调模型就需要 key，key 放 GitHub
   Secrets 就多一份要轮换的机密（`GEMINI_API_KEY` 因此被删掉）。本地跑用本机
   的凭据，仓库 Secrets 一个都不用加。
3. **失败看得见**：本地审查跑不出来时人就在旁边，直接重跑；跑在 CI 上失败则
   要翻日志才知道是模型抽风还是配置错。

> 代价要说清楚：**审查不再有机器强制**。以前 critical/high 会把 job 跑红、
> 直接卡住合并；现在它靠两件事兜住——本地审查时改干净，以及第 1 节的
> 「至少 1 个 approval + 不许绕过」。分支保护那两条必须真的配好，
> 否则这一层就等于没有。

## 5.1 重点审哪些文件（本地清单）

审查的**目标**是守住四条不变量：数据隔离（R1）、结算金额留痕（R3）、
状态机（R4）、权限提升（R5）。整个 PR 的 diff 里前端、测试、文档占了大头，
却几乎不可能踩到这四条，所以本地审查**只看高风险文件**：

| 范围 | 路径 |
| --- | --- |
| 高风险（**必审**） | `apps/api/alembic/`、`apps/api/app/services/`、`apps/api/app/core/auth.py`、`apps/api/app/api/v1/`、`apps/api/app/models/`、`apps/api/app/schemas/` |
| 低风险（**跳过**） | 前端（`apps/web-admin`、`apps/h5-*`、`packages/`）、测试文件、文档（`*.md`）、`openapi.json`、`schema.ts` |

`apps/api/app/schemas/` 在名单里，是因为**请求体校验层**也守着边界：
金额精度（`max_digits` / `decimal_places`）、`extra="forbid"`（不许客户端自报
operator）、`expected_status` 这些约束都写在那里——漏审它等于把结算金额的
口子留着。

低风险文件不是「不用看」，是**由 CI 的两个 job 兜住**：后端 job 跑单元 +
集成测试（集成测试不许静默 skip），前端 job 跑 typecheck / test / build。
测试全绿的低风险改动，放行没问题。

> 已知取舍：名单按目录粗粒度划，`apps/api/app/` 下不在名单里的目录
> （例如将来新增的 `app/tools/`）默认不审；要收进来就在本节表格里加一行。

## 6. 一次典型的合并流程

```bash
git switch feature/xxx
# 推之前先本地审查（规则见 code_review_agent/skills/code-review-and-quality/SKILL.md）
# critical / high 改干净再推
git add -A && git commit -m "feat(xxx): ..."
git push -u origin feature/xxx
gh pr create --base main --fill
# 等 CI：后端 / 前端 ×3 四个检查全绿
# 评审人 approve + 把评审里的问题回复完
gh pr merge --squash
```

推完代码后想看 CI 跑得怎么样：

```bash
gh pr checks <PR号> --watch
```
