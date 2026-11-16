/**
 * 按角色显示的界面（PLAT-02 修的 PLAT-01 遗留）。
 *
 * 两件事：
 *
 * 1. **标题按角色显示**：平台账号看到的是「平台管理后台」，
 *    服务商账号看到的是「服务商后台」——登录页与顶栏都是。
 *    写死一个名字会让人以为自己看错了地方。
 * 2. **菜单按角色收窄**：平台账号不该看到服务商的菜单
 *    （点进去会拿到 403），服务商账号不该看到平台的菜单。
 *
 * **前端的角色判断只是体验**：真正的边界在后端（服务端按 token 判，
 * 角色不对一律 403）。
 */
import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import App from "@/App.vue";
import LoginView from "@/views/LoginView.vue";
import type { CurrentUser } from "@/stores/session";

import { mockClient } from "./client-mock";
import { setupApp } from "./helpers";

vi.mock("@oto/shared/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@oto/shared/api")>();
  const { mockClient: client } = await import("./client-mock");
  return { ...actual, createApiClient: () => client };
});

const PLATFORM_ADMIN: CurrentUser = {
  id: 1,
  nickname: "平台管理员",
  phone: "13700000001",
  role: "PLATFORM_ADMIN",
  provider_id: null,
};

const PLATFORM_OPS: CurrentUser = {
  id: 2,
  nickname: "平台运营",
  phone: "13700000002",
  role: "PLATFORM_OPS",
  provider_id: null,
};

const PLATFORM_FINANCE: CurrentUser = {
  id: 4,
  nickname: "平台财务",
  phone: "13700000004",
  role: "PLATFORM_FINANCE",
  provider_id: null,
};

const PROVIDER_ADMIN: CurrentUser = {
  id: 3,
  nickname: "甲管理员",
  phone: "13800000001",
  role: "PROVIDER_ADMIN",
  provider_id: 301,
};

describe("按角色显示的界面", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    mockClient.login.mockResolvedValue({
      access_token: "issued-token",
      token_type: "bearer",
      user: {
        id: 7,
        nickname: "甲管理员",
        phone: "13800000001",
        role: "PROVIDER_ADMIN",
        provider_id: 3,
      },
    });
  });

  it("登录页标题按角色显示：平台账号是「平台管理后台」", async () => {
    const { pinia, router } = await setupApp("/login", {
      token: "",
      currentUser: PLATFORM_ADMIN,
    });
    const wrapper = mount(LoginView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    expect(wrapper.find('[data-test="login-title"]').text()).toBe("平台管理后台");
  });

  it("登录页标题按角色显示：服务商账号是「服务商后台」", async () => {
    const { pinia, router } = await setupApp("/login", {
      token: "",
      currentUser: PROVIDER_ADMIN,
    });
    const wrapper = mount(LoginView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    expect(wrapper.find('[data-test="login-title"]').text()).toBe("服务商后台");
  });

  it("顶栏标题按角色显示", async () => {
    const platform = await setupApp("/platform/orders", {
      currentUser: PLATFORM_ADMIN,
    });
    const platformWrapper = mount(App, {
      global: { plugins: [platform.pinia, platform.router] },
    });
    await flushPromises();
    expect(platformWrapper.find('[data-test="app-title"]').text()).toContain(
      "平台管理后台",
    );

    localStorage.clear();
    const provider = await setupApp("/provider/dispatch", {
      currentUser: PROVIDER_ADMIN,
    });
    const providerWrapper = mount(App, {
      global: { plugins: [provider.pinia, provider.router] },
    });
    await flushPromises();
    expect(providerWrapper.find('[data-test="app-title"]').text()).toContain(
      "服务商后台",
    );
  });

  it("平台账号看不到服务商菜单", async () => {
    const { pinia, router } = await setupApp("/platform/orders", {
      currentUser: PLATFORM_ADMIN,
    });
    const wrapper = mount(App, { global: { plugins: [pinia, router] } });
    await flushPromises();

    const nav = wrapper.find('[data-test="app-nav"]');
    expect(nav.text()).not.toContain("派单");
    expect(nav.text()).not.toContain("师傅管理");
    // 平台自己的菜单在
    expect(nav.find('[data-test="platform-orders-link"]').exists()).toBe(true);
    expect(nav.find('[data-test="platform-categories-link"]').exists()).toBe(true);
    expect(nav.find('[data-test="platform-providers-link"]').exists()).toBe(true);
  });

  it("平台运营看不到「服务商管理」（那是管理员的动作）", async () => {
    const { pinia, router } = await setupApp("/platform/orders", {
      currentUser: PLATFORM_OPS,
    });
    const wrapper = mount(App, { global: { plugins: [pinia, router] } });
    await flushPromises();

    const nav = wrapper.find('[data-test="app-nav"]');
    expect(nav.find('[data-test="platform-providers-link"]').exists()).toBe(false);
    expect(nav.find('[data-test="platform-orders-link"]').exists()).toBe(true);
    expect(nav.find('[data-test="platform-categories-link"]').exists()).toBe(true);
  });

  it("平台财务看得到「结算确认」，看不到运营页面", async () => {
    const { pinia, router } = await setupApp("/platform/settlements", {
      currentUser: PLATFORM_FINANCE,
    });
    const wrapper = mount(App, { global: { plugins: [pinia, router] } });
    await flushPromises();

    const nav = wrapper.find('[data-test="app-nav"]');
    expect(nav.find('[data-test="platform-settlements-link"]').exists()).toBe(true);
    // 订单总览 / 品类管理后端只放 PLATFORM_ADMIN / PLATFORM_OPS，
    // 财务点进去只会拿到 403，菜单就不显示了
    expect(nav.find('[data-test="platform-orders-link"]').exists()).toBe(false);
    expect(nav.find('[data-test="platform-categories-link"]').exists()).toBe(false);
    expect(nav.find('[data-test="platform-providers-link"]').exists()).toBe(false);
  });

  it("平台管理员也看得到「结算确认」", async () => {
    const { pinia, router } = await setupApp("/platform/orders", {
      currentUser: PLATFORM_ADMIN,
    });
    const wrapper = mount(App, { global: { plugins: [pinia, router] } });
    await flushPromises();

    const nav = wrapper.find('[data-test="app-nav"]');
    expect(nav.find('[data-test="platform-settlements-link"]').exists()).toBe(true);
  });

  it("服务商账号看不到平台菜单", async () => {
    const { pinia, router } = await setupApp("/provider/dispatch", {
      currentUser: PROVIDER_ADMIN,
    });
    const wrapper = mount(App, { global: { plugins: [pinia, router] } });
    await flushPromises();

    const nav = wrapper.find('[data-test="app-nav"]');
    expect(nav.text()).toContain("派单");
    expect(nav.text()).toContain("师傅管理");
    expect(nav.find('[data-test="platform-orders-link"]').exists()).toBe(false);
    expect(nav.find('[data-test="platform-categories-link"]').exists()).toBe(false);
    expect(nav.find('[data-test="platform-providers-link"]').exists()).toBe(false);
  });
});
