# packages/shared

跨端共享的类型定义、常量、工具函数与 API SDK。

## API SDK

```
src/api/schema.ts   自动生成（勿手改）：OpenAPI 契约 -> TypeScript 类型
src/api/client.ts   手写：基于上面那套类型的 fetch 封装
```

### 重新生成

后端接口变了，流程是：

```bash
make openapi                  # 1. 从 FastAPI 应用导出契约 -> apps/api/openapi.json
npm install                   # 2. 装依赖（openapi-typescript 在 packages/shared 的 devDependencies）
npm run generate:api          # 3. 生成 packages/shared/src/api/schema.ts
```

根目录的 `npm run generate:api` 会转发到 `@oto/shared` 这个 workspace
（根 package.json 的 workspaces 里已经有 `packages/*`）。

### 为什么生成物进版本库

`openapi-typescript` 是构建时工具，不要求每个前端开发者本地都装一遍依赖才能写代码。
契约变了的时候由改后端的人把 `apps/api/openapi.json` 和 `packages/shared/src/api/schema.ts`
一起提交，评审时能直接看到「接口变了」和「类型变了」是同一件事。

`apps/api/tests/api/test_openapi_contract.py` 会盯着 `openapi.json` 跟实际路由是否一致——
后端加了接口忘了重新导出，那条测试会先红。
