/**
 * 路由守卫的行为。
 *
 * 没有 token 时跳到登录页，并把原来要去的地方带在 redirect 上，
 * 登录完再跳回去（登录页自己处理 redirect）。
 */
import { describe, expect, it } from "vitest";

import { setupApp } from "./helpers";

describe("路由守卫", () => {
  it("没有 token 时跳到登录页", async () => {
    const { router } = await setupApp("/orders", { token: "" });

    expect(router.currentRoute.value.name).toBe("login");
    // 把原来要去的地方带过去，登录完可以跳回来
    expect(router.currentRoute.value.query.redirect).toBe("/orders");
  });

  it("有 token 时正常进入业务页面", async () => {
    const { router } = await setupApp("/orders");

    expect(router.currentRoute.value.path).toBe("/orders");
  });

  it("登录页本身不需要 token（否则拿不到 token）", async () => {
    const { router } = await setupApp("/login", { token: "" });

    expect(router.currentRoute.value.path).toBe("/login");
  });
});
