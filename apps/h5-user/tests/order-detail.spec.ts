/**
 * 必测 3：订单详情的「确认完成」。
 *
 * PENDING_CONFIRM 状态出现「确认完成」按钮，点击调 confirm 接口。
 */
import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import OrderDetailView from "@/views/OrderDetailView.vue";

import { mockClient } from "./client-mock";
import { setupApp } from "./helpers";

vi.mock("@oto/shared/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@oto/shared/api")>();
  const { mockClient: client } = await import("./client-mock");
  return { ...actual, createApiClient: () => client };
});

const ORDER_NO = "OTO2026010100001";

function orderDetail(status: string) {
  return {
    id: 1,
    order_no: ORDER_NO,
    status,
    pay_status: "UNPAID",
    amount: "99.00",
    item_id: 10,
    item_name: "日常保洁",
    slot_id: 20,
    slot_date: "2026-01-01",
    slot_start_time: "09:00:00",
    slot_end_time: "11:00:00",
    address_id: 1,
    created_at: "2026-01-01T00:00:00Z",
  };
}

describe("订单详情页", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockClient.getMyOrder.mockResolvedValue(orderDetail("PENDING_CONFIRM"));
    mockClient.confirmService.mockResolvedValue({
      order_no: ORDER_NO,
      status: "COMPLETED",
    });
  });

  it("PENDING_CONFIRM 时出现「确认完成」按钮，点击调确认接口", async () => {
    const { pinia, router } = await setupApp(`/orders/${ORDER_NO}`);

    const wrapper = mount(OrderDetailView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    const button = wrapper.find('[data-test="confirm-button"]');
    expect(button.exists()).toBe(true);
    expect(button.text()).toContain("确认完成");

    await button.trigger("click");
    await flushPromises();

    expect(mockClient.confirmService).toHaveBeenCalledTimes(1);
    expect(mockClient.confirmService).toHaveBeenCalledWith({ order_no: ORDER_NO });
  });

  it("不是待确认状态时不显示「确认完成」按钮", async () => {
    mockClient.getMyOrder.mockResolvedValue(orderDetail("IN_SERVICE"));

    const { pinia, router } = await setupApp(`/orders/${ORDER_NO}`);
    const wrapper = mount(OrderDetailView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    expect(wrapper.find('[data-test="confirm-button"]').exists()).toBe(false);
    expect(mockClient.confirmService).not.toHaveBeenCalled();
  });
});
