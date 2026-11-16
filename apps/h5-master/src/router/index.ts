/**
 * 路由表与路由守卫。
 *
 * 守卫有两个作用：
 *
 * 1. 没有 token 就不许进业务页面（跳到登录页）；
 * 2. 已经入职的师傅不许再走入驻申请页（直接送回订单页）。
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

import { api } from "@/api";
import { useSessionStore } from "@/stores/session";

export const routes = [
  { path: "/", redirect: "/orders" },
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
    path: "/onboard",
    name: "onboard",
    component: () => import("@/views/OnboardingView.vue"),
  },
  {
    path: "/login",
    name: "login",
    component: () => import("@/views/LoginView.vue"),
    // 公开页：不带 token 也要能进（否则守卫会把它再弹回去，死循环）
    meta: { public: true },
  },
];

/**
 * 这个人是不是**已经入职**（申请状态是 ACTIVE）。
 *
 * 为什么要问后端：角色在**登记申请时**就改成 MASTER 了
 * （见后端 app.services.master_onboarding），所以「角色是 MASTER」
 * 只说明他申请过，说明不了他有没有通过审核——通过与否看 master.status。
 *
 * 问不到（网络错 / 后端挂了）时**一律当作没入职**：守卫挡人的唯一
 * 后果是让一个本来能填表的人看到白屏，那比多一次申请糟糕得多。
 */
async function isActiveMaster(): Promise<boolean> {
  try {
    const application = await api.getMyOnboarding();
    return application.status === "ACTIVE";
  } catch {
    return false;
  }
}

export function createAppRouter(
  pinia: Pinia,
  history: RouterHistory = createWebHistory(),
): Router {
  const router = createRouter({ history, routes });

  router.beforeEach(async (to) => {
    if (to.meta.public === true) return true;
    const session = useSessionStore(pinia);
    if (!session.token) {
      // 带上原来要去的地方，登录完跳回来
      return { name: "login", query: { redirect: to.fullPath } };
    }
    // 已经入职的师傅不用再申请：直接去订单页接单
    if (to.name === "onboard" && session.currentUser?.role === "MASTER") {
      if (await isActiveMaster()) {
        return { name: "orders" };
      }
    }
    return true;
  });

  return router;
}
