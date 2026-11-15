/**
 * 平台侧订单总览页的测试（/platform/orders）。
 *
 * 必测点：
 *
 * 1. **表格渲染**：mock 返回 3 笔订单，表格出 3 行，订单号 / 服务商都对；
 * 2. **筛选切换触发重新请求**：改状态筛选 -> 重新拉一次，并且把新的筛选
 *    条件带进请求（这是「筛选是查询条件」的具体体现）。
 *
 * 另外钉一条边界：**前端不带 user_id**——订单总览是全量的，
 * 但「看全量」来自后端按角色放行，不来自客户端自报身份。
 */
import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ElSelect } from "element-plus";

import PlatformOrdersView from "@/views/PlatformOrdersView.vue";
import type { CurrentUser } from "@/stores/session";

import { mockClient } from "./client-mock";
import { setupApp } from "./helpers";

vi.mock("@oto/shared/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@oto/shared/api")>();
  const { mockClient: client } = await import("./client-mock");
  return { ...actual, createApiClient: () => client };
});

const ORDERS = {
  items: [
    {
      id: 501,
      order_no: "OTO20260101000001",
      status: "PENDING_DISPATCH",
      pay_status: "PAID",
      amount: "100.00",
      user_id: 7,
      provider_id: null,
      provider_name: null,
      item_id: 11,
      item_name: "日常保洁",
      created_at: "2026-01-01T10:00:00Z",
    },
    {
      id: 502,
      order_no: "OTO20260101000002",
      status: "IN_SERVICE",
      pay_status: "PAID",
      amount: "188.00",
      user_id: 8,
      provider_id: 301,
      provider_name: "甲服务商",
      item_id: 12,
      item_name: "深度保洁",
      created_at: "2026-01-02T10:00:00Z",
    },
    {
      id: 503,
      order_no: "OTO20260101000003",
      status: "COMPLETED",
      pay_status: "PAID",
      amount: "88.00",
      user_id: 9,
      provider_id: 302,
      provider_name: "乙服务商",
      item_id: 13,
      item_name: "月嫂服务",
      created_at: "2026-01-03T10:00:00Z",
    },
  ],
  total: 3,
  page: 1,
  limit: 20,
  providers: [
    { id: 301, name: "甲服务商" },
    { id: 302, name: "乙服务商" },
  ],
};

/** 平台运营（订单总览这页平台管理员与平台运营都能进）。 */
const PLATFORM_OPS = {
  id: 2,
  nickname: "平台运营",
  phone: "13700000002",
  role: "PLATFORM_OPS",
  provider_id: null,
};

async function mountPlatformPage(currentUser: CurrentUser = PLATFORM_OPS) {
  const { pinia } = await setupApp("/platform/orders", { currentUser });
  const wrapper = mount(PlatformOrdersView, {
    global: { plugins: [pinia] },
  });
  await flushPromises();
  return { wrapper };
}

describe("平台侧订单总览页", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    mockClient.listPlatformOrders.mockResolvedValue(ORDERS);
  });

  it("表格渲染：订单号、服务商、服务项都对", async () => {
    const { wrapper } = await mountPlatformPage();

    const rows = wrapper.findAll(".el-table__body-wrapper tbody tr");
    expect(rows).toHaveLength(3);
    expect(wrapper.text()).toContain("OTO20260101000001");
    expect(wrapper.text()).toContain("甲服务商");
    expect(wrapper.text()).toContain("乙服务商");
    expect(wrapper.text()).toContain("日常保洁");
    // 还没派的单：服务商显示成「未派单」而不是空白
    expect(wrapper.text()).toContain("（未派单）");
  });

  it("首次加载：按第一页拉一次，不带 user_id", async () => {
    await mountPlatformPage();

    expect(mockClient.listPlatformOrders).toHaveBeenCalledTimes(1);
    const params = mockClient.listPlatformOrders.mock.calls[0][0];
    expect(params.page).toBe(1);
    expect(params.status).toBeUndefined();
    expect(params.provider_id).toBeUndefined();
    // 平台看全量靠的是角色，不是客户端自报身份
    expect(params).not.toHaveProperty("user_id");
  });

  it("切换状态筛选：重新请求，并把新筛选条件带进请求", async () => {
    const { wrapper } = await mountPlatformPage();
    expect(mockClient.listPlatformOrders).toHaveBeenCalledTimes(1);

    const statusSelect = wrapper
      .find('[data-test="status-filter"]')
      .findComponent(ElSelect);
    statusSelect.vm.$emit("update:modelValue", "COMPLETED");
    await flushPromises();

    expect(mockClient.listPlatformOrders).toHaveBeenCalledTimes(2);
    const params = mockClient.listPlatformOrders.mock.calls[1][0];
    expect(params.status).toBe("COMPLETED");
    // 筛选变了要回到第一页，不然会停在一个不存在的页码上
    expect(params.page).toBe(1);
  });

  it("切换服务商筛选：重新请求，并带上服务商 id", async () => {
    const { wrapper } = await mountPlatformPage();

    const providerSelect = wrapper
      .find('[data-test="provider-filter"]')
      .findComponent(ElSelect);
    providerSelect.vm.$emit("update:modelValue", 301);
    await flushPromises();

    expect(mockClient.listPlatformOrders).toHaveBeenCalledTimes(2);
    expect(mockClient.listPlatformOrders.mock.calls[1][0].provider_id).toBe(301);
  });
});
