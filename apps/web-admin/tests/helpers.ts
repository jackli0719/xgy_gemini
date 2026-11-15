/**
 * 测试用的应用装配。
 *
 * 页面不是「装个组件」就完事：它们要用路由（跳转）和 pinia（会话）。
 * 这里统一造一套：memory 路由 + 独立 pinia 实例，并预置一个 token。
 */
import { createPinia, setActivePinia, type Pinia } from "pinia";
import { createMemoryHistory, type Router } from "vue-router";
import { expect, vi } from "vitest";

import { createAppRouter } from "@/router";
import type { CurrentUser } from "@/stores/session";

export interface SetupOptions {
  /** 是否预置 token（默认预置）。不预置时路由守卫会跳到「请先登录」。 */
  token?: string;
  /**
   * 预置当前登录用户（默认不预置）。
   *
   * 有角色门槛的页面（``meta.requiresRole``）靠它过守卫：
   * 守卫读的是会话 store 里的 role，而 store 是从 localStorage 读的。
   */
  currentUser?: CurrentUser;
}

export interface SetupResult {
  pinia: Pinia;
  router: Router;
}

/**
 * 造一套 pinia + 路由，并导航到 path。
 *
 * 返回前已经 `await router.isReady()`，所以挂载组件时路由是就绪的。
 */
export async function setupApp(
  path: string,
  options: SetupOptions = {},
): Promise<SetupResult> {
  const token = options.token === undefined ? "test-token" : options.token;
  if (token) {
    localStorage.setItem("oto.web.token", token);
  } else {
    localStorage.removeItem("oto.web.token");
  }
  if (options.currentUser) {
    localStorage.setItem("oto.web.currentUser", JSON.stringify(options.currentUser));
  } else {
    localStorage.removeItem("oto.web.currentUser");
  }

  const pinia = createPinia();
  // 让 useSessionStore()（不带参数的写法）也拿到同一个实例
  setActivePinia(pinia);

  const router = createAppRouter(pinia, createMemoryHistory());
  await router.push(path);
  await router.isReady();

  return { pinia, router };
}

/**
 * 等路由真的走到某个 path。
 *
 * 页面是懒加载的（路由表里 component 是动态 import），
 * 一次跳转要先把组件 chunk 拉进来才结束 —— flushPromises 之类的一次
 * 微任务刷新等不到它完成，直接断言会偶发失败。这里轮询等它落地。
 */
export async function waitForPath(router: Router, path: string): Promise<void> {
  await vi.waitFor(() => {
    expect(router.currentRoute.value.path).toBe(path);
  });
}
