/**
 * 我的订单列表页（卡片流程的第 4 步）。
 *
 * 不在必测之列，但列表页是「下单后跳过去」的地方，
 * 顺手钉住：渲染出订单、点进去是详情页。
 */
import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import OrdersView from "@/views/OrdersView.vue";

import { mockClient } from "./client-mock";
import { setupApp, waitForPath } from "./helpers";

vi.mock("@oto/shared/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@oto/shared/api")>();
  const { mockClient: client } = await import("./client-mock");
  return { ...actual, createApiClient: () => client };
});

function orderItem(orderNo: string, name: string) {
  return {
    order_no: orderNo,
    status: "PENDING_PAY",
    pay_status: "UNPAID",
    amount: "99.00",
    item_id: 10,
    item_name: name,
    slot_date: "2026-01-01",
    slot_start_time: "09:00:00",
    created_at: "2026-01-01T00:00:00Z",
  };
}

describe("我的订单页", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockClient.listMyOrders.mockResolvedValue({
      items: [orderItem("OTO2026010100001", "日常保洁"), orderItem("OTO2026010100002", "深度保洁")],
      // 总数给 25：一页 20 条，说明还有下一页可翻
      total: 25,
      limit: 20,
      offset: 0,
    });
  });

  it("渲染出订单列表", async () => {
    const { pinia, router } = await setupApp("/orders");

    const wrapper = mount(OrdersView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    const items = wrapper.findAll('[data-test="order-item"]');
    expect(items).toHaveLength(2);
    expect(items[0].text()).toContain("日常保洁");
    expect(wrapper.find('[data-test="page-meta"]').text()).toContain("共 25 条");
  });

  it("点订单跳到详情页", async () => {
    const { pinia, router } = await setupApp("/orders");

    const wrapper = mount(OrdersView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    await wrapper.findAll('[data-test="order-item"]')[0].trigger("click");
    await waitForPath(router, "/orders/OTO2026010100001");
  });

  it("翻页时把 offset 传给后端", async () => {
    const { pinia, router } = await setupApp("/orders");

    const wrapper = mount(OrdersView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    expect(mockClient.listMyOrders).toHaveBeenCalledWith({ limit: 20, offset: 0 });

    await wrapper.find('[data-test="next-page"]').trigger("click");
    await flushPromises();

    expect(mockClient.listMyOrders).toHaveBeenLastCalledWith({ limit: 20, offset: 20 });
  });
});
