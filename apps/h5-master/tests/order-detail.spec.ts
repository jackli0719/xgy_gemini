/**
 * 订单详情页（师傅端）。
 *
 * 顺手钉住：详情带客户联系方式与上门地址（师傅要上门），
 * 以及「按状态给按钮」——不该出现的按钮不出现。
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

function detail(status: "PENDING_ACCEPT" | "ACCEPTED" | "IN_SERVICE") {
  return {
    id: 1,
    order_no: "OTO20260101000001",
    status,
    amount: "99.00",
    item_id: 10,
    item_name: "日常保洁",
    slot_id: 3,
    slot_date: "2026-01-01",
    slot_start_time: "09:00:00",
    slot_end_time: "12:00:00",
    created_at: "2026-01-01T00:00:00Z",
    customer_contact: "张三",
    customer_phone: "13900000001",
    address_region: "北京市朝阳区",
    address_detail: "建国路 88 号",
  };
}

describe("订单详情页（师傅端）", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockClient.getMasterOrder.mockResolvedValue(detail("ACCEPTED"));
    mockClient.startService.mockResolvedValue({
      order_no: "OTO20260101000001",
      status: "IN_SERVICE",
      completed_at: null,
    });
  });

  it("渲染订单信息与上门地址", async () => {
    const { pinia, router } = await setupApp("/orders/OTO20260101000001");

    const wrapper = mount(OrderDetailView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    expect(wrapper.find('[data-test="order-no"]').text()).toContain(
      "OTO20260101000001",
    );
    expect(wrapper.find('[data-test="customer"]').text()).toContain("张三");
    expect(wrapper.find('[data-test="address"]').text()).toContain("北京市朝阳区");
  });

  it("已接单的订单给「开始服务」按钮，点它调 startService", async () => {
    const { pinia, router } = await setupApp("/orders/OTO20260101000001");

    const wrapper = mount(OrderDetailView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    expect(wrapper.find('[data-test="start-button"]').exists()).toBe(true);
    expect(wrapper.find('[data-test="accept-button"]').exists()).toBe(false);

    await wrapper.find('[data-test="start-button"]').trigger("click");
    await flushPromises();

    expect(mockClient.startService).toHaveBeenCalledWith({
      order_no: "OTO20260101000001",
    });
  });

  it("待接单的订单给「接单 / 拒单」按钮", async () => {
    mockClient.getMasterOrder.mockResolvedValue(detail("PENDING_ACCEPT"));
    const { pinia, router } = await setupApp("/orders/OTO20260101000001");

    const wrapper = mount(OrderDetailView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    expect(wrapper.find('[data-test="accept-button"]').exists()).toBe(true);
    expect(wrapper.find('[data-test="reject-button"]').exists()).toBe(true);
    expect(wrapper.find('[data-test="start-button"]').exists()).toBe(false);
  });
});
