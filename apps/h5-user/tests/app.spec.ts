/**
 * 应用外壳的冒烟测试。
 *
 * App.vue 里挂了导航栏和底部 tabbar（router 模式），
 * 这两个是全局注册的组件，光有页面测试盖不住 —— 这里整体挂一次，
 * 确认外壳能渲染、router-view 能把当前页面放出来。
 */
import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import App from "@/App.vue";

import { mockClient } from "./client-mock";
import { setupApp } from "./helpers";

vi.mock("@oto/shared/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@oto/shared/api")>();
  const { mockClient: client } = await import("./client-mock");
  return { ...actual, createApiClient: () => client };
});

describe("应用外壳", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockClient.listCategories.mockResolvedValue([]);
  });

  it("渲染导航栏和当前页面", async () => {
    const { pinia, router } = await setupApp("/catalog");

    const wrapper = mount(App, { global: { plugins: [pinia, router] } });
    await flushPromises();

    expect(wrapper.text()).toContain("OTO 家政");
    // router-view 里放的是当前路由对应的页面
    expect(wrapper.find(".van-tabbar").exists()).toBe(true);
    expect(wrapper.text()).toContain("选择服务品类");
  });
});
