/**
 * 路由守卫的行为。
 *
 * 没有 token 时跳到登录页，并把原来要去的地方带在 redirect 上，
 * 登录完再跳回去（登录页自己处理 redirect）。
 */
import { describe, expect, it } from "vitest";

import { setupApp } from "./helpers";

// 超时从默认的 5s 放宽到 10s：这几个用例都要等懒加载的路由 chunk
// （登录页 / 业务页）真正拉下来。满负荷跑整套时，冷启动 + 转译要把
// 3.5s 拉到 5s 以上，5s 上限会偶发翻车——测试本身是绿的，只是慢。
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
}, 10000);
