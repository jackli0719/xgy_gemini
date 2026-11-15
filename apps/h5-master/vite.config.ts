import { fileURLToPath, URL } from "node:url";

import vue from "@vitejs/plugin-vue";
import Components from "unplugin-vue-components/vite";
import { VantResolver } from "unplugin-vue-components/resolvers";
import { defineConfig } from "vitest/config";

/**
 * 师傅端 H5 构建 / 测试配置。
 *
 * 与用户端（apps/h5-user）同一套骨架，只有端口不同（5174 vs 5173）：
 * 两个应用可以同时开着调试。
 *
 * 两个 alias：
 *
 * - `@` -> src/：源码内部用 `@/api` 这种短路径；
 * - `@oto/shared/api` -> packages/shared/src/api/index.ts：
 *   直接指到**源码**而不是包入口，指到源码可以让 vite / vitest
 *   直接走 TS 编译链，不受 node_modules 里「默认不转译依赖」的限制。
 */
export default defineConfig({
  plugins: [
    vue(),
    // Vant 组件按需自动引入：模板里写 <van-cell>，编译时自动 import
    // 对应组件和它的样式（不用手写 import，也不用整包注册）。
    // dts 会生成 src/components.d.ts（进版本库），vue-tsc 才有模板类型。
    Components({
      resolvers: [VantResolver()],
      dts: "src/components.d.ts",
    }),
  ],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
      "@oto/shared/api": fileURLToPath(
        new URL("../../packages/shared/src/api/index.ts", import.meta.url),
      ),
    },
  },
  server: {
    port: 5174,
    // 开发时把 /api 代理到本地跑着的 FastAPI（uvicorn 默认 8000）。
    // CORS_ORIGINS 里需要放行 http://localhost:5174（见根目录 .env）。
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
    // 依赖要 inline（走 vite 转译，而不是交给 node 原生加载）：
    // - vant 的 es 产物里 import 了 .css，node 原生加载会报
    //   "Unknown file extension .css"；
    // - @oto/shared 是 workspace 里的 TS 源码，也要转译。
    server: {
      deps: {
        inline: ["vant", /@oto\/shared/],
      },
    },
  },
});
