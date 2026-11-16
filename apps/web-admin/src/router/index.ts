/**
 * 路由表与路由守卫。
 *
 * 守卫管三件事：
 *
 * 1. **没有 token 不许进业务页面**（跳到登录页）。
 * 2. **角色不对不许进某些页面**（`meta.requiresRoles`）。
 *    服务商侧页面只有服务商角色能进，平台侧页面只有平台角色能进。
 * 3. **首页按角色落地**：平台账号回平台页，服务商账号回派单页。
 *
 * **登录页自己带 redirect**：没登录时想去哪，登录完再回哪。
 *
 * 前端的角色判断只是**体验**（别让不该看的人看到菜单），
 * 真正的边界在后端：服务端按 token 里的 role 判，
 * 角色不对一律 403。前端这层漏了也只是多点一下、多一个报错。
 *
 * createAppRouter 接收一个显式的 pinia 实例，守卫与首页重定向里用
 * `useSessionStore(pinia)` 取 store——不依赖「当前活跃的 pinia」，
 * 这样在测试里可以随意造实例。
 */
import type { Pinia } from "pinia";
import {
  createRouter,
  createWebHistory,
  type RouteRecordRaw,
  type Router,
  type RouterHistory,
} from "vue-router";

import { useSessionStore } from "@/stores/session";
import {
  PLATFORM_ADMIN,
  PLATFORM_FINANCE,
  PLATFORM_ROLES,
  PROVIDER_ROLES,
  homePathForRole,
} from "@/utils/role";

/**
 * 造路由表。
 *
 * **路由表在函数里造，不放在模块级**：首页的重定向要读会话里的角色，
 * 而会话 store 得绑定到一个具体的 pinia 实例上（守卫用的就是这个实例）。
 */
export function buildRoutes(pinia: Pinia): RouteRecordRaw[] {
  return [
    {
      path: "/",
      // 重定向按**角色**决定：平台账号回平台页，服务商账号回派单页。
      // 认不出角色的一律去登录页（宁可重新登录，也别落到一个跟角色不搭的页面）。
      redirect: () => homePathForRole(useSessionStore(pinia).currentUser?.role),
    },
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
      meta: { requiresRoles: [...PROVIDER_ROLES] },
    },
    {
      path: "/provider/masters",
      name: "provider-masters",
      component: () => import("@/views/ProviderMastersView.vue"),
      meta: { requiresRoles: [...PROVIDER_ROLES] },
    },
    {
      path: "/platform/providers",
      name: "platform-providers",
      component: () => import("@/views/PlatformProvidersView.vue"),
      // 服务商入驻 / 冻结是管理动作，只有平台管理员能进
      meta: { requiresRoles: [PLATFORM_ADMIN] },
    },
    {
      path: "/platform/settlements",
      name: "platform-settlements",
      component: () => import("@/views/PlatformSettlementsView.vue"),
      // 结算确认：平台财务与平台管理员都能进这页
      // （列表接口后端也放这两个角色；只有「确认结算」那一步限财务）
      meta: { requiresRoles: [PLATFORM_FINANCE, PLATFORM_ADMIN] },
    },
    {
      path: "/platform/orders",
      name: "platform-orders",
      component: () => import("@/views/PlatformOrdersView.vue"),
      // 订单总览：平台管理员与平台运营都能看
      meta: { requiresRoles: [...PLATFORM_ROLES] },
    },
    {
      path: "/platform/categories",
      name: "platform-categories",
      component: () => import("@/views/PlatformCategoriesView.vue"),
      // 品类管理（含改价）：平台管理员与平台运营都能管
      meta: { requiresRoles: [...PLATFORM_ROLES] },
    },
  ];
}

export function createAppRouter(
  pinia: Pinia,
  history: RouterHistory = createWebHistory(),
): Router {
  const router = createRouter({ history, routes: buildRoutes(pinia) });

  router.beforeEach((to) => {
    if (to.meta.public === true) return true;
    const session = useSessionStore(pinia);
    if (!session.token) {
      // 带上原来要去的地方，登录完跳回来
      return { name: "login", query: { redirect: to.fullPath } };
    }
    // 角色不对：回首页（首页按角色落到对应的工作台）。
    // 这只是体验层的拦截，真正的边界在后端（403）。
    const requiredRoles = to.meta.requiresRoles;
    if (
      Array.isArray(requiredRoles) &&
      requiredRoles.length > 0 &&
      !requiredRoles.includes(session.currentUser?.role ?? "")
    ) {
      return { path: "/" };
    }
    return true;
  });

  return router;
}
