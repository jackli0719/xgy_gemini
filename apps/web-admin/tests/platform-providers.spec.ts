/**
 * 必测 4（平台侧服务商管理页）：
 *
 * 1. **列表渲染 + 状态按钮按 status 显示**：mock 返回 3 个服务商，
 *    表格出 3 行；每行的动作按钮按状态给（PENDING=审核通过 /
 *    ACTIVE=冻结 / FROZEN=解冻）；
 * 2. **新建服务商**：点「新建服务商」-> 填表 -> 调 createProvider，
 *    参数正确；成功后**刷新列表**（listPlatformProviders 被调 2 次）。
 *
 * 另外钉两条边界：
 *
 * - **前端不带 operator / 身份字段**：操作人身份由后端按 token 决定，
 *   请求参数里只有服务商 id 与状态（卡片约束 1）；
 * - **角色不对进不了这页**：路由守卫按 role 拦（PLATFORM_ADMIN）。
 */
import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import PlatformProvidersView from "@/views/PlatformProvidersView.vue";
import type { CurrentUser } from "@/stores/session";

import { mockClient } from "./client-mock";
import { setupApp, waitForPath } from "./helpers";

vi.mock("@oto/shared/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@oto/shared/api")>();
  const { mockClient: client } = await import("./client-mock");
  return { ...actual, createApiClient: () => client };
});

const PROVIDERS = {
  items: [
    {
      id: 301,
      name: "甲服务商",
      contact_phone: "13900000001",
      commission_rate: "0.1500",
      status: "PENDING",
      created_at: "2026-01-01T10:00:00Z",
    },
    {
      id: 302,
      name: "乙服务商",
      contact_phone: "13900000002",
      commission_rate: "0.2000",
      status: "ACTIVE",
      created_at: "2026-01-02T10:00:00Z",
    },
    {
      id: 303,
      name: "丙服务商",
      contact_phone: "13900000003",
      commission_rate: "0.1000",
      status: "FROZEN",
      created_at: "2026-01-03T10:00:00Z",
    },
  ],
  total: 3,
  page: 1,
  limit: 20,
};

/** 平台管理员（这页只有这个角色能进）。 */
const PLATFORM_ADMIN = {
  id: 1,
  nickname: "平台管理员",
  phone: "13700000001",
  role: "PLATFORM_ADMIN",
  provider_id: null,
};

async function mountPlatformPage(currentUser: CurrentUser = PLATFORM_ADMIN) {
  const { pinia, router } = await setupApp("/platform/providers", { currentUser });
  const wrapper = mount(PlatformProvidersView, {
    global: { plugins: [pinia] },
  });
  await flushPromises();
  return { wrapper, router };
}

describe("平台侧服务商管理页", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    mockClient.listPlatformProviders.mockResolvedValue(PROVIDERS);
    mockClient.createProvider.mockResolvedValue(PROVIDERS.items[0]);
    mockClient.updateProviderStatus.mockResolvedValue(PROVIDERS.items[1]);
    mockClient.createProviderAdmin.mockResolvedValue({
      id: 900,
      phone: "13900000009",
      role: "PROVIDER_ADMIN",
      provider_id: 301,
      created_at: "2026-01-04T10:00:00Z",
    });
  });

  it("列表渲染 + 状态按钮按 status 显示", async () => {
    const { wrapper } = await mountPlatformPage();

    const rows = wrapper.findAll(".el-table__body-wrapper tbody tr");
    expect(rows).toHaveLength(3);
    expect(wrapper.text()).toContain("甲服务商");
    expect(wrapper.text()).toContain("乙服务商");
    expect(wrapper.text()).toContain("丙服务商");

    // 每行一个动作按钮，文案按当前状态给
    const actions = wrapper.findAll('[data-test="status-action-btn"]');
    expect(actions).toHaveLength(3);
    expect(actions[0].text()).toContain("审核通过");
    expect(actions[1].text()).toContain("冻结");
    expect(actions[2].text()).toContain("解冻");
  });

  it("新建服务商：调 createProvider 参数正确，成功后刷新列表", async () => {
    const { wrapper } = await mountPlatformPage();
    expect(mockClient.listPlatformProviders).toHaveBeenCalledTimes(1);

    await wrapper.find('[data-test="create-provider-btn"]').trigger("click");
    await flushPromises();
    expect(wrapper.find('[data-test="create-provider-dialog"]').exists()).toBe(true);

    await wrapper.find('[data-test="provider-name-field"] input').setValue("丁服务商");
    await wrapper.find('[data-test="provider-phone-field"] input').setValue("13900000009");
    await wrapper.find('[data-test="provider-rate-field"] input').setValue("0.18");
    await flushPromises();

    await wrapper.find('[data-test="submit-provider-btn"]').trigger("click");
    await flushPromises();

    expect(mockClient.createProvider).toHaveBeenCalledTimes(1);
    expect(mockClient.createProvider).toHaveBeenCalledWith({
      name: "丁服务商",
      contact_phone: "13900000009",
      commission_rate: 0.18,
    });
    // 表格里的状态以服务端为准：不刷新就会看到幽灵数据
    expect(mockClient.listPlatformProviders).toHaveBeenCalledTimes(2);
  });

  it("点「审核通过」：调 PATCH 只带服务商 id 与状态", async () => {
    const { wrapper } = await mountPlatformPage();

    await wrapper.findAll('[data-test="status-action-btn"]')[0].trigger("click");
    await flushPromises();

    expect(mockClient.updateProviderStatus).toHaveBeenCalledTimes(1);
    expect(mockClient.updateProviderStatus).toHaveBeenCalledWith(
      { provider_id: 301 },
      { status: "ACTIVE" },
    );
    // 操作人身份由后端按 token 决定，前端不传
    const params = mockClient.updateProviderStatus.mock.calls[0][0];
    expect(params).not.toHaveProperty("operator");
    expect(params).not.toHaveProperty("operator_id");
  });

  it("点「冻结」与「解冻」：状态分别是 FROZEN 与 ACTIVE", async () => {
    const { wrapper } = await mountPlatformPage();

    await wrapper.findAll('[data-test="status-action-btn"]')[1].trigger("click");
    await flushPromises();
    expect(mockClient.updateProviderStatus).toHaveBeenLastCalledWith(
      { provider_id: 302 },
      { status: "FROZEN" },
    );

    await wrapper.findAll('[data-test="status-action-btn"]')[2].trigger("click");
    await flushPromises();
    expect(mockClient.updateProviderStatus).toHaveBeenLastCalledWith(
      { provider_id: 303 },
      { status: "ACTIVE" },
    );
  });

  it("创建管理员：弹窗填手机号 -> 调 createProviderAdmin", async () => {
    const { wrapper } = await mountPlatformPage();

    await wrapper.findAll('[data-test="create-admin-btn"]')[0].trigger("click");
    await flushPromises();
    expect(wrapper.find('[data-test="create-admin-dialog"]').exists()).toBe(true);

    await wrapper.find('[data-test="admin-phone-field"] input').setValue("13900000009");
    await flushPromises();

    await wrapper.find('[data-test="submit-admin-btn"]').trigger("click");
    await flushPromises();

    expect(mockClient.createProviderAdmin).toHaveBeenCalledTimes(1);
    expect(mockClient.createProviderAdmin).toHaveBeenCalledWith(
      { provider_id: 301 },
      { phone: "13900000009" },
    );
  });

  it("角色不是平台管理员：路由守卫不放行这页", async () => {
    const { router } = await mountPlatformPage({
      id: 2,
      nickname: "服务商管理员",
      role: "PROVIDER_ADMIN",
      provider_id: 301,
    });

    // 被弹回首页（首页再落到派单页）
    await waitForPath(router, "/provider/dispatch");
  });
});
