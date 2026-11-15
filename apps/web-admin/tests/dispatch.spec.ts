/**
 * 必测 3（派单页）：
 *
 * 1. **派单列表渲染**：mock 返回 2 笔，表格出 2 行；
 * 2. **派单弹窗**：选师傅 -> 调 dispatch 接口，参数正确；
 * 3. **派单成功 -> 列表刷新**（listOrders 被调 2 次）。
 *
 * 另外钉一条边界：**前端不带 provider_id**——请求参数里只有状态和分页，
 * 归属由后端按 token 决定（卡片约束 1）。
 */
import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ProviderDispatchView from "@/views/ProviderDispatchView.vue";

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
      id: 101,
      order_no: "OTO20260101000001",
      status: "PENDING_DISPATCH",
      pay_status: "PAID",
      amount: "100.00",
      item_id: 5,
      item_name: "日常保洁",
      slot_date: "2026-01-02",
      slot_start_time: "09:00:00",
      created_at: "2026-01-01T10:00:00Z",
    },
    {
      id: 102,
      order_no: "OTO20260101000002",
      status: "PENDING_DISPATCH",
      pay_status: "PAID",
      amount: "200.00",
      item_id: 6,
      item_name: "深度保洁",
      slot_date: "2026-01-02",
      slot_start_time: "14:00:00",
      created_at: "2026-01-01T11:00:00Z",
    },
  ],
  total: 2,
  limit: 20,
  offset: 0,
};

const MASTERS = {
  items: [
    {
      id: 201,
      real_name: "师傅甲",
      phone: "13800000005",
      rating: "4.5",
      status: "ACTIVE",
    },
    {
      id: 202,
      real_name: "师傅乙",
      phone: "13800000006",
      rating: null,
      status: "PENDING",
    },
  ],
  total: 2,
};

async function mountDispatchPage() {
  const { pinia } = await setupApp("/provider/dispatch");
  const wrapper = mount(ProviderDispatchView, {
    global: { plugins: [pinia] },
  });
  await flushPromises();
  return wrapper;
}

/** 打开某行的派单弹窗、选中第 index 个师傅、确认派单。 */
async function dispatchTo(wrapper: Awaited<ReturnType<typeof mountDispatchPage>>, index: number) {
  await wrapper.findAll('[data-test="dispatch-btn"]')[0].trigger("click");
  await flushPromises();

  await wrapper.find('[data-test="master-select"] input').trigger("click");
  await flushPromises();

  const options = wrapper.findAll(".el-select-dropdown__item");
  await options[index].trigger("click");
  await flushPromises();

  await wrapper.find('[data-test="dispatch-confirm"]').trigger("click");
  await flushPromises();
}

describe("派单页", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    mockClient.listProviderOrders.mockResolvedValue(ORDERS);
    mockClient.listProviderMasters.mockResolvedValue(MASTERS);
    mockClient.dispatchOrder.mockResolvedValue({
      order_no: "OTO20260101000001",
      status: "PENDING_ACCEPT",
      master_id: 202,
    });
  });

  it("派单列表渲染：两笔订单出两行", async () => {
    const wrapper = await mountDispatchPage();

    const rows = wrapper.findAll(".el-table__body-wrapper tbody tr");
    expect(rows).toHaveLength(2);
    expect(wrapper.text()).toContain("OTO20260101000001");
    expect(wrapper.text()).toContain("OTO20260101000002");
  });

  it("列表请求不带 provider_id：归属由后端按 token 决定", async () => {
    await mountDispatchPage();

    expect(mockClient.listProviderOrders).toHaveBeenCalledTimes(1);
    const params = mockClient.listProviderOrders.mock.calls[0][0];
    expect(params).toEqual({ status: "PENDING_DISPATCH" });
    expect(params).not.toHaveProperty("provider_id");
  });

  it("派单弹窗：选师傅后调 dispatch 接口，参数正确", async () => {
    const wrapper = await mountDispatchPage();

    // 弹窗默认没开
    expect(wrapper.find('[data-test="dispatch-dialog"]').exists()).toBe(false);

    await wrapper.findAll('[data-test="dispatch-btn"]')[0].trigger("click");
    await flushPromises();
    expect(wrapper.find('[data-test="dispatch-dialog"]').exists()).toBe(true);

    // 选第二个师傅（师傅乙，id=202）
    await wrapper.find('[data-test="master-select"] input').trigger("click");
    await flushPromises();
    const options = wrapper.findAll(".el-select-dropdown__item");
    expect(options).toHaveLength(2);
    await options[1].trigger("click");
    await flushPromises();

    await wrapper.find('[data-test="dispatch-confirm"]').trigger("click");
    await flushPromises();

    expect(mockClient.dispatchOrder).toHaveBeenCalledTimes(1);
    // 第一行的订单 id 是 101，选中的师傅 id 是 202
    expect(mockClient.dispatchOrder).toHaveBeenCalledWith(
      { order_id: 101 },
      { master_id: 202 },
    );
  });

  it("派单成功后刷新列表（listOrders 被调 2 次）", async () => {
    const wrapper = await mountDispatchPage();
    expect(mockClient.listProviderOrders).toHaveBeenCalledTimes(1);

    await dispatchTo(wrapper, 1);

    expect(mockClient.dispatchOrder).toHaveBeenCalledTimes(1);
    // 派出去的订单已经不在待派单池里：不刷新就会看到幽灵数据
    expect(mockClient.listProviderOrders).toHaveBeenCalledTimes(2);
  });
});
