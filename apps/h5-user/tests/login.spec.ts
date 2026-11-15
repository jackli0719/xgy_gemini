/**
 * 必测 4：登录成功跳 redirect。
 *
 * 钉住三件事：
 * - 登录成功把 token 写进会话（localStorage）；
 * - 跳回 redirect 指向的地方（没 redirect 就回品类页）；
 * - 验证码不对时留在登录页并显示错误文案。
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

const LOGIN_RESULT = {
  access_token: "issued-token",
  token_type: "bearer",
  user: { id: 7, nickname: "体验用户", phone: "13800000001" },
};

describe("登录页", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    mockClient.login.mockResolvedValue(LOGIN_RESULT);
  });

  it("登录成功后跳回 redirect 指定的地方", async () => {
    const { pinia, router } = await setupApp("/login?redirect=/orders", { token: "" });

    const wrapper = mount(LoginView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    await wrapper.find('[data-test="phone-field"] input').setValue("13800000001");
    await wrapper.find('[data-test="code-field"] input').setValue("123456");
    await flushPromises();

    await wrapper.find('[data-test="submit-login"]').trigger("click");
    await flushPromises();

    expect(mockClient.login).toHaveBeenCalledWith({
      phone: "13800000001",
      code: "123456",
    });
    // token 落在 localStorage 里（会话 store）
    expect(localStorage.getItem("oto.token")).toBe("issued-token");
    // 跳回原来要去的地方
    await waitForPath(router, "/orders");
  });

  it("没有 redirect 时登录后回品类页", async () => {
    const { pinia, router } = await setupApp("/login", { token: "" });

    const wrapper = mount(LoginView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    await wrapper.find('[data-test="phone-field"] input').setValue("13800000001");
    await wrapper.find('[data-test="code-field"] input').setValue("123456");
    await flushPromises();

    await wrapper.find('[data-test="submit-login"]').trigger("click");
    await flushPromises();

    await waitForPath(router, "/catalog");
  });

  it("验证码错误时留在登录页并显示错误文案", async () => {
    mockClient.login.mockRejectedValue(new Error("验证码错误或已过期"));

    const { pinia, router } = await setupApp("/login?redirect=/orders", { token: "" });
    const wrapper = mount(LoginView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    await wrapper.find('[data-test="phone-field"] input').setValue("13800000001");
    await wrapper.find('[data-test="code-field"] input').setValue("000000");
    await flushPromises();

    await wrapper.find('[data-test="submit-login"]').trigger("click");
    await flushPromises();

    expect(router.currentRoute.value.path).toBe("/login");
    expect(wrapper.find('[data-test="error"]').text()).toContain("验证码错误");
    expect(localStorage.getItem("oto.token")).toBeNull();
  });

  it("没填手机号就不发请求", async () => {
    const { pinia, router } = await setupApp("/login", { token: "" });
    const wrapper = mount(LoginView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    await wrapper.find('[data-test="submit-login"]').trigger("click");
    await flushPromises();

    expect(mockClient.login).not.toHaveBeenCalled();
    expect(wrapper.find('[data-test="error"]').text()).toContain("请填写手机号");
  });
});
