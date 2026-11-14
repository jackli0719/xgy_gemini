/**
 * 登录占位的守卫行为（卡片约束 C）。
 *
 * 本卡不写登录页：没有 token 时提示「请先登录」。
 */
import { describe, expect, it } from "vitest";

import { setupApp } from "./helpers";

describe("路由守卫", () => {
  it("没有 token 时跳到「请先登录」", async () => {
    const { router } = await setupApp("/orders", { token: "" });

    expect(router.currentRoute.value.name).toBe("need-login");
    // 把原来要去的地方带过去，登录页上线后可以跳回来
    expect(router.currentRoute.value.query.redirect).toBe("/orders");
  });

  it("有 token 时正常进入业务页面", async () => {
    const { router } = await setupApp("/orders");

    expect(router.currentRoute.value.path).toBe("/orders");
  });
});
