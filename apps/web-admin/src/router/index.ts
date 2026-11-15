/**
 * 路由表与路由守卫。
 *
 * 守卫管两件事：
 *
 * 1. **没有 token 不许进业务页面**（跳到登录页）。
 * 2. **角色不对不许进某些页面**（`meta.requiresRole`）。
 *    平台侧的服务商管理页只有 PLATFORM_ADMIN 能进。
 *
 * **登录页自己带 redirect**：没登录时想去哪，登录完再回哪。
 *
 * 前端的角色判断只是**体验**（别让不该看的人看到菜单），
 * 真正的边界在后端：服务端按 token 里的 role 判，
 * 角色不对一律 403。前端这层漏了也只是多点一下、多一个报错。
 *
 * createAppRouter 接收一个显式的 pinia 实例，守卫里用 `useSessionStore(pinia)`
 * 取 store——不依赖「当前活跃的 pinia」，这样在测试里可以随意造实例。
 */
import type { Pinia } from "pinia";
import {
  createRouter,
  createWebHistory,
  type Router,
  type RouterHistory,
} from "vue-router";

import { useSessionStore } from "@/stores/session";

export const routes = [
  { path: "/", redirect: "/provider/dispatch" },
  {
    path: "/login",
    name: "login",
    component: () => import("@/views/LoginView.vue"),
    // 公开页：不带 token 也要能进（否则守卫会把它再弹回去，死循环）
    meta: { public: true },
  },
  {
    path: "/provider/dispatch",
    name: "provider-dispatch",
    component: () => import("@/views/ProviderDispatchView.vue"),
  },
  {
    path: "/provider/masters",
    name: "provider-masters",
    component: () => import("@/views/ProviderMastersView.vue"),
  },
  {
    path: "/platform/providers",
    name: "platform-providers",
    component: () => import("@/views/PlatformProvidersView.vue"),
    // 只有平台管理员能进这页
    meta: { requiresRole: "PLATFORM_ADMIN" },
  },
];

export function createAppRouter(
  pinia: Pinia,
  history: RouterHistory = createWebHistory(),
): Router {
  const router = createRouter({ history, routes });

  router.beforeEach((to) => {
    if (to.meta.public === true) return true;
    const session = useSessionStore(pinia);
    if (!session.token) {
      // 带上原来要去的地方，登录完跳回来
      return { name: "login", query: { redirect: to.fullPath } };
    }
    // 角色不对：回首页（首页会落到派单页）。
    // 这只是体验层的拦截，真正的边界在后端（403）。
    const requiredRole = to.meta.requiresRole;
    if (typeof requiredRole === "string" && session.currentUser?.role !== requiredRole) {
      return { path: "/" };
    }
    return true;
  });

  return router;
}
