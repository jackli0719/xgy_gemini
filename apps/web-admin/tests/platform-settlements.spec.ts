/**
 * 平台侧结算确认页的测试（/platform/settlements）。
 *
 * 必测点：
 *
 * 1. **列表渲染**：mock 返回 2 张结算单，表格出 2 行，服务商 / 金额 / 状态都对；
 * 2. **筛选切换触发重新请求**：改状态 / 服务商筛选 -> 重新拉一次，
 *    并把新的筛选条件带进请求（这是「筛选是查询条件」的具体体现）；
 * 3. **确认按钮只在 PENDING 行显示**：已确认的行显示确认时间；
 *    点「确认结算」-> 调 confirmSettlement 且带上正确的 settlement_id
 *    -> 刷新列表；
 * 4. **平台管理员看得见列表、但没有确认按钮**（看得到 ≠ 确认得了：
 *    确认接口只放平台财务）。
 */
import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ElButton, ElSelect } from "element-plus";

import PlatformSettlementsView from "@/views/PlatformSettlementsView.vue";
import type { CurrentUser } from "@/stores/session";

import { mockClient } from "./client-mock";
import { setupApp } from "./helpers";

vi.mock("@oto/shared/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@oto/shared/api")>();
  const { mockClient: client } = await import("./client-mock");
  return { ...actual, createApiClient: () => client };
});

const SETTLEMENTS = {
  items: [
    {
      id: 901,
      provider_name: "甲服务商",
      period_start: "2026-01-01",
      period_end: "2026-01-31",
      total_amount: "1000.00",
      commission_amount: "100.00",
      net_amount: "900.00",
      status: "PENDING",
      confirmed_at: null,
    },
    {
      id: 902,
      provider_name: "乙服务商",
      period_start: "2026-02-01",
      period_end: "2026-02-28",
      total_amount: "500.00",
      commission_amount: "50.00",
      net_amount: "450.00",
      status: "CONFIRMED",
      confirmed_at: "2026-03-01T08:00:00Z",
    },
  ],
  total: 2,
  page: 1,
  limit: 20,
  providers: [
    { id: 301, name: "甲服务商" },
    { id: 302, name: "乙服务商" },
  ],
};

/** 平台财务（结算确认这页的主角：能看，也能确认）。 */
const PLATFORM_FINANCE: CurrentUser = {
  id: 4,
  nickname: "平台财务",
  phone: "13700000004",
  role: "PLATFORM_FINANCE",
  provider_id: null,
};

/** 平台管理员（能看列表，但不能确认——确认只归财务）。 */
const PLATFORM_ADMIN: CurrentUser = {
  id: 2,
  nickname: "平台管理员",
  phone: "13700000002",
  role: "PLATFORM_ADMIN",
  provider_id: null,
};

async function mountSettlementPage(currentUser: CurrentUser = PLATFORM_FINANCE) {
  const { pinia } = await setupApp("/platform/settlements", { currentUser });
  const wrapper = mount(PlatformSettlementsView, {
    global: { plugins: [pinia] },
  });
  await flushPromises();
  return { wrapper };
}

describe("平台侧结算确认页", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    mockClient.listPlatformSettlements.mockResolvedValue(SETTLEMENTS);
    mockClient.confirmSettlement.mockResolvedValue({
      id: 901,
      status: "CONFIRMED",
      net_amount: "900.00",
      confirmed_at: "2026-03-02T09:00:00Z",
    });
  });

  it("列表渲染：服务商、金额、状态都对", async () => {
    const { wrapper } = await mountSettlementPage();

    const rows = wrapper.findAll(".el-table__body-wrapper tbody tr");
    expect(rows).toHaveLength(2);
    expect(wrapper.text()).toContain("甲服务商");
    expect(wrapper.text()).toContain("乙服务商");
    // 金额三件套
    expect(wrapper.text()).toContain("1000.00");
    expect(wrapper.text()).toContain("100.00");
    expect(wrapper.text()).toContain("900.00");
    // 状态文案
    expect(wrapper.text()).toContain("待结算");
    expect(wrapper.text()).toContain("已确认");
    // 结算周期
    expect(wrapper.text()).toContain("2026-01-01 ~ 2026-01-31");
  });

  it("首次加载：按第一页拉一次，不带筛选条件", async () => {
    await mountSettlementPage();

    expect(mockClient.listPlatformSettlements).toHaveBeenCalledTimes(1);
    const params = mockClient.listPlatformSettlements.mock.calls[0][0];
    expect(params.page).toBe(1);
    expect(params.status).toBeUndefined();
    expect(params.provider_id).toBeUndefined();
  });

  it("切换状态筛选：重新请求，并把新筛选条件带进请求", async () => {
    const { wrapper } = await mountSettlementPage();
    expect(mockClient.listPlatformSettlements).toHaveBeenCalledTimes(1);

    const statusSelect = wrapper
      .find('[data-test="status-filter"]')
      .findComponent(ElSelect);
    statusSelect.vm.$emit("update:modelValue", "PENDING");
    await flushPromises();

    expect(mockClient.listPlatformSettlements).toHaveBeenCalledTimes(2);
    const params = mockClient.listPlatformSettlements.mock.calls[1][0];
    expect(params.status).toBe("PENDING");
    // 筛选变了要回到第一页
    expect(params.page).toBe(1);
  });

  it("切换服务商筛选：重新请求，并带上服务商 id", async () => {
    const { wrapper } = await mountSettlementPage();

    const providerSelect = wrapper
      .find('[data-test="provider-filter"]')
      .findComponent(ElSelect);
    providerSelect.vm.$emit("update:modelValue", 301);
    await flushPromises();

    expect(mockClient.listPlatformSettlements).toHaveBeenCalledTimes(2);
    expect(mockClient.listPlatformSettlements.mock.calls[1][0].provider_id).toBe(301);
  });

  it("确认按钮只在 PENDING 行显示，已确认的行显示确认时间", async () => {
    const { wrapper } = await mountSettlementPage();

    const buttons = wrapper.findAll('[data-test="confirm-button"]');
    expect(buttons).toHaveLength(1);
    expect(buttons[0].text()).toBe("确认结算");

    // 已确认的那一行显示确认时间，不显示按钮
    const confirmedAt = wrapper.find('[data-test="confirmed-at"]');
    expect(confirmedAt.exists()).toBe(true);
    expect(confirmedAt.text()).not.toBe("");
  });

  it("点确认：带上正确的 settlement_id 调确认接口，然后刷新列表", async () => {
    const { wrapper } = await mountSettlementPage();
    expect(mockClient.listPlatformSettlements).toHaveBeenCalledTimes(1);

    const button = wrapper
      .findAll('[data-test="confirm-button"]')[0]
      .findComponent(ElButton);
    await button.trigger("click");
    await flushPromises();

    expect(mockClient.confirmSettlement).toHaveBeenCalledTimes(1);
    expect(mockClient.confirmSettlement).toHaveBeenCalledWith({
      settlement_id: 901,
    });
    // 确认完要重新拉列表（列表里的状态才是真的）
    expect(mockClient.listPlatformSettlements).toHaveBeenCalledTimes(2);
  });

  it("确认失败：把服务端的话显示出来，并刷新列表", async () => {
    const { ApiError } = await import("@oto/shared/api");
    mockClient.confirmSettlement.mockRejectedValue(
      new ApiError(404, "结算单不存在：settlement_id=901", null),
    );
    const { wrapper } = await mountSettlementPage();

    const button = wrapper
      .findAll('[data-test="confirm-button"]')[0]
      .findComponent(ElButton);
    await button.trigger("click");
    await flushPromises();

    expect(wrapper.find('[data-test="error"]').text()).toContain(
      "结算单不存在",
    );
    // 失败也刷新：服务端说这张单已经不在「待结算」了，列表要跟上
    expect(mockClient.listPlatformSettlements).toHaveBeenCalledTimes(2);
  });

  it("平台管理员：看得见列表，但没有「确认结算」按钮", async () => {
    const { wrapper } = await mountSettlementPage(PLATFORM_ADMIN);

    // 列表照常拉、照常渲染
    expect(mockClient.listPlatformSettlements).toHaveBeenCalledTimes(1);
    const rows = wrapper.findAll(".el-table__body-wrapper tbody tr");
    expect(rows).toHaveLength(2);
    expect(wrapper.text()).toContain("甲服务商");

    // 但没有确认按钮：确认接口只放平台财务，前端不给这个入口
    expect(wrapper.findAll('[data-test="confirm-button"]')).toHaveLength(0);
    // 待结算的那行写明原因，而不是空着
    expect(wrapper.find('[data-test="finance-only-hint"]').text()).toBe(
      "仅财务可确认",
    );
  });
});
