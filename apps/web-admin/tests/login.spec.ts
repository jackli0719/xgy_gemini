/**
 * 登录页的测试。
 *
 * 卡片要求「不写完整登录页，复用 FE-03 的 /api/v1/auth/login」，
 * 所以这里只钉三件事：
 * - 登录成功把 token 与 currentUser（含 provider_id）写进会话；
 * - 跳回 redirect 指定的地方；
 * - 验证码错误时留在登录页并显示后端给的文案。
 */
import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@oto/shared/api";

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
  user: {
    id: 7,
    nickname: "甲管理员",
    phone: "13800000001",
    role: "PROVIDER_ADMIN",
    provider_id: 3,
  },
};

describe("登录页", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    mockClient.login.mockResolvedValue(LOGIN_RESULT);
  });

  it("登录成功后把 token 与归属写进会话，跳回 redirect", async () => {
    const { pinia, router } = await setupApp("/login?redirect=/provider/dispatch", {
      token: "",
    });

    const wrapper = mount(LoginView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    await wrapper.find('[data-test="phone-field"]').setValue("13800000001");
    await wrapper.find('[data-test="code-field"]').setValue("123456");
    await flushPromises();

    await wrapper.find('[data-test="submit-login"]').trigger("click");
    await flushPromises();

    expect(mockClient.login).toHaveBeenCalledWith({
      phone: "13800000001",
      code: "123456",
    });
    expect(localStorage.getItem("oto.web.token")).toBe("issued-token");
    // currentUser 带 provider_id：后台要靠它显示「我在哪个服务商名下」
    expect(JSON.parse(localStorage.getItem("oto.web.currentUser") ?? "{}")).toEqual(
      LOGIN_RESULT.user,
    );
    await waitForPath(router, "/provider/dispatch");
  });

  it("没有 redirect 时登录后回派单页", async () => {
    const { pinia, router } = await setupApp("/login", { token: "" });

    const wrapper = mount(LoginView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    await wrapper.find('[data-test="phone-field"]').setValue("13800000001");
    await wrapper.find('[data-test="code-field"]').setValue("123456");
    await flushPromises();
    await wrapper.find('[data-test="submit-login"]').trigger("click");
    await flushPromises();

    await waitForPath(router, "/provider/dispatch");
  });

  it("redirect 是站外地址时不跟过去", async () => {
    const { pinia, router } = await setupApp("/login?redirect=//evil.example.com", {
      token: "",
    });

    const wrapper = mount(LoginView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    await wrapper.find('[data-test="phone-field"]').setValue("13800000001");
    await wrapper.find('[data-test="code-field"]').setValue("123456");
    await flushPromises();
    await wrapper.find('[data-test="submit-login"]').trigger("click");
    await flushPromises();

    await waitForPath(router, "/provider/dispatch");
  });

  it("验证码错误时留在登录页并显示错误文案", async () => {
    // SDK 对非 2xx 一律抛 ApiError，文案取后端返回的 detail
    mockClient.login.mockRejectedValue(
      new ApiError(401, "验证码错误或已过期", { detail: "验证码错误或已过期" }),
    );

    const { pinia, router } = await setupApp("/login", { token: "" });
    const wrapper = mount(LoginView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    await wrapper.find('[data-test="phone-field"]').setValue("13800000001");
    await wrapper.find('[data-test="code-field"]').setValue("000000");
    await flushPromises();
    await wrapper.find('[data-test="submit-login"]').trigger("click");
    await flushPromises();

    expect(router.currentRoute.value.path).toBe("/login");
    expect(wrapper.find('[data-test="error"]').text()).toContain("验证码错误");
    expect(localStorage.getItem("oto.web.token")).toBeNull();
  });
});
