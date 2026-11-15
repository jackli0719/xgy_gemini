/**
 * 路由表与路由守卫。
 *
 * 守卫的作用只有一个：没有 token 就不许进业务页面（跳到登录页）。
 *
 * **登录页自己带 redirect**：没登录时想去哪，登录完再回哪。
 * redirect 只允许站内绝对路径（判断在 LoginView 里）。
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
  { path: "/", redirect: "/catalog" },
  {
    path: "/catalog",
    name: "catalog",
    component: () => import("@/views/CatalogView.vue"),
  },
  {
    path: "/catalog/:id",
    name: "category-items",
    component: () => import("@/views/CategoryItemsView.vue"),
  },
  {
    path: "/order/new",
    name: "order-new",
    component: () => import("@/views/OrderNewView.vue"),
  },
  {
    path: "/orders",
    name: "orders",
    component: () => import("@/views/OrdersView.vue"),
  },
  {
    path: "/orders/:orderNo",
    name: "order-detail",
    component: () => import("@/views/OrderDetailView.vue"),
  },
  {
    path: "/addresses",
    name: "addresses",
    component: () => import("@/views/AddressesView.vue"),
  },
  {
    path: "/login",
    name: "login",
    component: () => import("@/views/LoginView.vue"),
    // 公开页：不带 token 也要能进（否则守卫会把它再弹回去，死循环）
    meta: { public: true },
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
    return true;
  });

  return router;
}
