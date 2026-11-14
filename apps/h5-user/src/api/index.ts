/**
 * API 客户端实例 —— **整个 H5 唯一的 HTTP 出口**。
 *
 * 约束（卡片明确要求）：不手写 fetch，全部走 @oto/shared 的 client。
 * 这个文件只做两件事：把 SDK 的 client 造出来、把 token 喂给它。
 *
 * baseUrl 默认空字符串 = 相对路径：开发时由 vite 的 proxy 把 /api 转发到
 * 本地后端（见 vite.config.ts）；部署时同源，也不用改。
 */
import { createApiClient } from "@oto/shared/api";

import { useSessionStore } from "@/stores/session";

/** 后端根地址。留空即相对路径（默认）。 */
const baseUrl = import.meta.env.VITE_API_BASE_URL ?? "";

export const api = createApiClient({
  baseUrl,
  /**
   * token 从会话 store 取（store 本身落在 localStorage）。
   * 没有 token 就不带 Authorization 头——后端会返回 401，
   * 前端靠路由守卫提前拦掉（见 router/index.ts）。
   */
  getToken: () => useSessionStore().token,
});

export type { ApiClient } from "@oto/shared/api";
