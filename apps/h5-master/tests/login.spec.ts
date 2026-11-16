/**
 * 登录页（师傅端）。
 *
 * 顺手钉住：登录成功后 token 落 localStorage、跳回订单页。
 */
import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import LoginView from "@/views/LoginView.vue";

import { mockClient } from "./client-mock";
import { setupApp, waitForPath } from "./helpers";

vi.mock("@oto/shared/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@oto/shared/api")>();
  const { mockClient: client } = await import("./client-mock");
  return { ...actual, createApiClient: () => client };
});

describe("登录页（师傅端）", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockClient.login.mockResolvedValue({
      access_token: "token-abc",
      token_type: "bearer",
      user: {
        id: 4,
        nickname: "张师傅",
        phone: "13900000002",
        role: "MASTER",
        provider_id: null,
      },
    });
  });

  it("登录成功后存 token 并跳到订单页", async () => {
    const { pinia, router } = await setupApp("/login");

    const wrapper = mount(LoginView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    await wrapper.find('[data-test="phone-field"] input').setValue("13900000002");
    await wrapper.find('[data-test="code-field"] input').setValue("123456");
    await wrapper.find('[data-test="submit-login"]').trigger("click");
    await flushPromises();

    expect(mockClient.login).toHaveBeenCalledWith({
      phone: "13900000002",
      code: "123456",
    });
    expect(localStorage.getItem("oto.master.token")).toBe("token-abc");
    await waitForPath(router, "/orders");
  });

  it("还不是师傅的账号 -> 登录后落到申请入驻页", async () => {
    // 还没入职的账号（role=USER）：订单接口对它来说是 403，
    // 师傅端唯一能进的页面就是入驻申请页
    mockClient.login.mockResolvedValue({
      access_token: "token-user",
      token_type: "bearer",
      user: {
        id: 9,
        nickname: "李师傅",
        phone: "13900000009",
        role: "USER",
        provider_id: null,
      },
    });
    const { pinia, router } = await setupApp("/login");

    const wrapper = mount(LoginView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    await wrapper.find('[data-test="phone-field"] input').setValue("13900000009");
    await wrapper.find('[data-test="code-field"] input').setValue("123456");
    await wrapper.find('[data-test="submit-login"]').trigger("click");
    await flushPromises();

    await waitForPath(router, "/onboard");
  });
});
