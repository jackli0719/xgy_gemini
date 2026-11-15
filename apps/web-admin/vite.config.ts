import { fileURLToPath, URL } from "node:url";

import vue from "@vitejs/plugin-vue";
import { defineConfig } from "vitest/config";

/**
 * 服务商 Web 后台的构建 / 测试配置。
 *
 * 两个 alias：
 *
 * - `@` -> src/：源码内部用 `@/api` 这种短路径；
 * - `@oto/shared/api` -> packages/shared/src/api/index.ts：
 *   直接指到**源码**而不是包入口，让 vite / vitest 走 TS 编译链，
 *   不受 node_modules 里「默认不转译依赖」的限制。
 */
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
      "@oto/shared/api": fileURLToPath(
        new URL("../../packages/shared/src/api/index.ts", import.meta.url),
      ),
    },
  },
  server: {
    // 5174：用户端 H5 占着 5173
    port: 5174,
    // 开发时把 /api 代理到本地跑着的 FastAPI（uvicorn 默认 8000）
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
  build: {
    target: "es2020",
  },
  test: {
    environment: "jsdom",
    globals: true,
    include: ["tests/**/*.spec.ts"],
    server: {
      deps: {
        // Element Plus 的 es 产物是纯 ESM，但体量大且内部依赖多，
        // 交给 vite 转译比让 node 原生加载更稳（尤其是它的 popper 层）。
        inline: ["element-plus"],
      },
    },
  },
});
