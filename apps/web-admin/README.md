# apps/web-admin

Web 管理后台（Vue3 + Element Plus），平台端与服务商端共用，按 provider_id 隔离数据与菜单。

当前进度（PLAT-01）：**平台侧服务商管理页**（服务商列表 / 新建 / 审核 / 冻结 / 建管理员账号）。

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
| `src/router/index.ts` | 路由表 + 守卫：`/login`（公开）、`/provider/dispatch`（要 token）、`/platform/providers`（要 `PLATFORM_ADMIN` 角色） |
| `src/stores/session.ts` | pinia 会话 store：token + currentUser（含 `provider_id`、`role`） |
| `src/api/index.ts` | 唯一的 HTTP 出口，SDK 实例（`@oto/shared`） |
| `src/views/LoginView.vue` | 登录页（薄壳，复用 FE-03 的 `/api/v1/auth/login`） |
| `src/views/ProviderDispatchView.vue` | 派单页：待派单列表 + 派单弹窗 |
| `src/views/PlatformProvidersView.vue` | 平台侧服务商管理页：列表 + 新建 / 审核 / 冻结 / 建管理员 |

## 三条边界

1. **前端不带 `provider_id`**：服务商归属由后端按 token 决定
   （`require_provider_scope`）。前端就算往 query 里塞 `provider_id`
   也没用——接口压根没这个入参。
2. **平台侧接口只认 `PLATFORM_ADMIN`**：路由守卫按 role 拦（菜单也按角色显示），
   但那只是体验层——真正的边界在后端（`require_platform_admin`，角色不对一律 403）。
   「管哪一个服务商」是路径参数 `provider_id`，**操作人身份永远只从 token 来**。
3. **HTTP 只走 `@oto/shared` 的 SDK**：不手写 fetch。类型从
   `apps/api/openapi.json` 生成（`make openapi && npm run generate:api -w @oto/shared`），
   后端加了接口忘了重新导出，契约检查测试会先红。
