/**
 * 应用外壳的冒烟测试（师傅端）。
 *
 * 这里只钉一件事：**「申请入驻」的入口在不在**。
 *
 * 入驻申请页是师傅端唯一的「还没入职的人能进的页面」，真实链路上
 * 没人能走到它就等于没做——所以入口必须钉住：
 *
 * - 拿不到师傅资料（还没入职的账号）-> 导航栏给「申请入驻」入口；
 * - 已入职（ACTIVE）-> 不给这个入口（没得申请了）。
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

describe("应用外壳（师傅端）", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("还没入职（拿不到师傅资料）-> 导航栏有「申请入驻」入口", async () => {
    mockClient.getMasterProfile.mockRejectedValue(new Error("Forbidden"));
    const { pinia, router } = await setupApp("/orders");

    const wrapper = mount(App, { global: { plugins: [pinia, router] } });
    await flushPromises();

    const link = wrapper.find('[data-test="onboard-link"]');
    expect(link.exists()).toBe(true);
    expect(link.attributes("href")).toBe("/onboard");
  });

  it("已入职（ACTIVE）-> 不给「申请入驻」入口", async () => {
    mockClient.getMasterProfile.mockResolvedValue({
      real_name: "张师傅",
      provider_name: "甲服务商",
      status: "ACTIVE",
      rating: "4.5",
    });
    const { pinia, router } = await setupApp("/orders");

    const wrapper = mount(App, { global: { plugins: [pinia, router] } });
    await flushPromises();

    expect(wrapper.find('[data-test="onboard-link"]').exists()).toBe(false);
  });
});
