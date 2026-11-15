# apps/web-admin

Web 管理后台（Vue3 + Element Plus），平台端与服务商端共用，按 provider_id 隔离数据与菜单。

当前进度（PLAT-02）：

- **平台侧服务商管理页**（服务商列表 / 新建 / 审核 / 冻结 / 建管理员账号，PLAT-01）
- **平台侧订单总览页**（全量订单，可按状态 / 服务商筛选，PLAT-02）
- **平台侧品类管理页**（品类树 + 服务项列表，新建 / 编辑 / 改价，PLAT-02）

平台侧页面分两种权限：

| 页面 | 能进的角色 |
| --- | --- |
| `/platform/providers` 服务商管理 | `PLATFORM_ADMIN` |
| `/platform/orders` 订单总览 | `PLATFORM_ADMIN` / `PLATFORM_OPS` |
| `/platform/categories` 品类管理 | `PLATFORM_ADMIN` / `PLATFORM_OPS` |

菜单与标题都按角色走：平台账号看的是「平台管理后台」，服务商账号看的是
「服务商后台」，两边看到的菜单也不一样（PLAT-02 修的 PLAT-01 遗留）。

## 跑起来

```bash
npm install                       # 仓库根目录，装齐 workspaces
npm run dev --workspace @oto/web-admin   # 开发服务器，端口见 e2e/README.md
make web-test                     # 前端测试（vitest）
make web-typecheck                # 类型检查（vue-tsc）
```

开发时 `/api` 由 vite 代理到本地后端（`http://localhost:8000`，见 `vite.config.ts`）。

## 目录

| 路径 | 说明 |
| --- | --- |
| `src/router/index.ts` | 路由表 + 守卫：`/login`（公开）、`/provider/*`（要 token + 服务商角色）、`/platform/*`（要 token + 平台角色）；首页按角色落地 |
| `src/stores/session.ts` | pinia 会话 store：token + currentUser（含 `provider_id`、`role`） |
| `src/utils/role.ts` | 角色常量与判断（菜单 / 守卫 / 标题共用的同一份事实） |
| `src/api/index.ts` | 唯一的 HTTP 出口，SDK 实例（`@oto/shared`） |
| `src/views/LoginView.vue` | 登录页（薄壳，复用 FE-03 的 `/api/v1/auth/login`），标题按角色显示 |
| `src/views/ProviderDispatchView.vue` | 派单页：待派单列表 + 派单弹窗 |
| `src/views/PlatformProvidersView.vue` | 平台侧服务商管理页：列表 + 新建 / 审核 / 冻结 / 建管理员 |
| `src/views/PlatformOrdersView.vue` | 平台侧订单总览页：全量订单 + 状态 / 服务商筛选 + 分页 |
| `src/views/PlatformCategoriesView.vue` | 平台侧品类管理页：品类树 + 服务项列表 + 新建 / 编辑 / 改价 |

## 三条边界

1. **前端不带 `provider_id`**：服务商归属由后端按 token 决定
   （`require_provider_scope`）。前端就算往 query 里塞 `provider_id`
   也没用——接口压根没这个入参。
2. **平台侧接口按角色分层**：服务商管理只认 `PLATFORM_ADMIN`
   （`require_platform_admin`），订单总览与品类管理认 `PLATFORM_ADMIN` /
   `PLATFORM_OPS`（`require_platform_staff`）。路由守卫按 role 拦
   （菜单也按角色显示），但那只是体验层——真正的边界在后端，角色不对一律 403。
   「管哪一个」是路径参数（`provider_id` / `category_id` / `item_id`），
   **操作人身份永远只从 token 来**。
   订单总览是**全量**（不按用户过滤）：平台特权来自角色，不是来自请求参数，
   所以前端不传 `user_id`。
3. **HTTP 只走 `@oto/shared` 的 SDK**：不手写 fetch。类型从
   `apps/api/openapi.json` 生成（`make openapi && npm run generate:api -w @oto/shared`），
   后端加了接口忘了重新导出，契约检查测试会先红。

## 改品类 / 改服务项的两个乐观锁字段

`PATCH /api/v1/platform/categories/{id}` 与 `/items/{id}` 带两个字段：

| 字段 | 是什么 | 不传会怎样 |
| --- | --- | --- |
| `expected_status` | 我以为的旧状态 | 用服务端刚读到的旧状态 |
| `expected_updated_at` | 我以为的**版本号**（这一行最后被改的时间，从列表接口原样带回） | 用服务端刚读到的版本号 |

服务端用**条件 UPDATE**（`WHERE id = ? AND status = ? AND 版本号 = ?`）判定，
一行都没改到就返回 409。**为什么两个都要**：状态没变但价格被别人改了，
只判状态是发现不了的——两个人的页面都显示「启用」，第二个人的改价会把
第一个人的改价无声地盖掉。版本号管的是「这一行有没有被别人动过」。

版本号取**毫秒**精度：前端经过 JS 的 `Date` 只会剩下毫秒，
定得更细就会出现「明明没冲突却报 409」。
