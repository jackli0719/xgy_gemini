/**
 * 我的订单页（师傅端）。
 *
 * 必测的四个点都在这里：
 *
 * 1. 接单列表渲染：mock 返回 2 笔 PENDING_ACCEPT，列表 2 行；
 * 2. 接单：点「接单」-> 调 acceptOrder({ order_no }) -> 列表刷新；
 * 3. 拒单：弹窗填原因 -> 调 rejectOrder，参数含 reason；
 * 4. 开始服务：ACCEPTED 分组点「开始服务」-> 调 startService。
 */
import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import OrdersView from "@/views/OrdersView.vue";

import { mockClient } from "./client-mock";
import { setupApp } from "./helpers";

vi.mock("@oto/shared/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@oto/shared/api")>();
  const { mockClient: client } = await import("./client-mock");
  return { ...actual, createApiClient: () => client };
});

/** 一笔订单（字段与后端 MasterOrderItem 对齐）。 */
function orderItem(
  orderNo: string,
  status: "PENDING_ACCEPT" | "ACCEPTED" | "IN_SERVICE",
  name = "日常保洁",
) {
  return {
    order_no: orderNo,
    status,
    amount: "99.00",
    item_id: 10,
    item_name: name,
    slot_date: "2026-01-01",
    slot_start_time: "09:00:00",
    slot_end_time: "12:00:00",
    created_at: "2026-01-01T00:00:00Z",
  };
}

const PENDING_ORDERS = [
  orderItem("OTO20260101000001", "PENDING_ACCEPT"),
  orderItem("OTO20260101000002", "PENDING_ACCEPT", "深度保洁"),
];
const ACCEPTED_ORDERS = [orderItem("OTO20260101000004", "ACCEPTED")];

describe("我的订单页（师傅端）", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // 按状态返回不同的列表：三个分组各有各的单
    mockClient.listMasterOrders.mockImplementation(
      async ({ status }: { status: string }) => {
        if (status === "ACCEPTED") {
          return { items: ACCEPTED_ORDERS, total: 1, limit: 20, offset: 0 };
        }
        if (status === "IN_SERVICE") {
          return { items: [], total: 0, limit: 20, offset: 0 };
        }
        return { items: PENDING_ORDERS, total: 2, limit: 20, offset: 0 };
      },
    );
    mockClient.acceptOrder.mockResolvedValue({
      order_no: "OTO20260101000001",
      status: "ACCEPTED",
      master_id: 1,
    });
    mockClient.rejectOrder.mockResolvedValue({
      order_no: "OTO20260101000001",
      status: "PENDING_DISPATCH",
      master_id: null,
    });
    mockClient.startService.mockResolvedValue({
      order_no: "OTO20260101000004",
      status: "IN_SERVICE",
      completed_at: null,
    });
  });

  it("渲染出接单列表（2 笔待接单 = 2 行）", async () => {
    const { pinia, router } = await setupApp("/orders");

    const wrapper = mount(OrdersView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    const items = wrapper.findAll('[data-test="order-item"]');
    expect(items).toHaveLength(2);
    expect(items[0].text()).toContain("日常保洁");
    expect(items[1].text()).toContain("深度保洁");
    // 列表只带自己的单：请求里不传 master_id
    expect(mockClient.listMasterOrders).toHaveBeenCalledWith({
      status: "PENDING_ACCEPT",
    });
  });

  it("点接单 -> 调 acceptOrder -> 刷新列表", async () => {
    const { pinia, router } = await setupApp("/orders");

    const wrapper = mount(OrdersView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    const callsBefore = mockClient.listMasterOrders.mock.calls.length;
    await wrapper.find('[data-test="accept-btn"]').trigger("click");
    await flushPromises();

    expect(mockClient.acceptOrder).toHaveBeenCalledWith({
      order_no: "OTO20260101000001",
    });
    // 刷新列表：接单之后重新拉一次待接单
    expect(mockClient.listMasterOrders.mock.calls.length).toBeGreaterThan(callsBefore);
    expect(mockClient.listMasterOrders).toHaveBeenLastCalledWith({
      status: "ACCEPTED",
    });
  });

  it("点拒单 -> 弹窗填原因 -> 调 rejectOrder（参数含 reason）", async () => {
    const { pinia, router } = await setupApp("/orders");

    const wrapper = mount(OrdersView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    await wrapper.find('[data-test="reject-btn"]').trigger("click");
    await flushPromises();

    // 弹窗里的原因输入框
    await wrapper.find('[data-test="reject-reason"] input').setValue("临时有事");
    await wrapper.find('[data-test="reject-confirm"]').trigger("click");
    await flushPromises();

    expect(mockClient.rejectOrder).toHaveBeenCalledWith(
      { order_no: "OTO20260101000001" },
      { reason: "临时有事" },
    );
  });

  it("ACCEPTED 分组点开始服务 -> 调 startService", async () => {
    const { pinia, router } = await setupApp("/orders");

    const wrapper = mount(OrdersView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    // 切到「待服务」分组（第二个 tab）
    await wrapper.findAll(".van-tab")[1].trigger("click");
    await vi.waitFor(() => {
      expect(wrapper.find('[data-test="start-btn"]').exists()).toBe(true);
    });

    await wrapper.find('[data-test="start-btn"]').trigger("click");
    await flushPromises();

    expect(mockClient.startService).toHaveBeenCalledWith({
      order_no: "OTO20260101000004",
    });
  });
});
