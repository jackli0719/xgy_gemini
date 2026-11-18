/**
 * 我的订单页（师傅端）。
 *
 * 必测的点都在这里：
 *
 * 1. 接单列表渲染：mock 返回 2 笔 PENDING_ACCEPT，列表 2 行；
 * 2. 接单：点「接单」-> 调 acceptOrder({ order_no }) -> 列表刷新；
 * 3. 拒单：弹窗填原因 -> 调 rejectOrder，参数含 reason；
 * 4. 开始服务：ACCEPTED 分组点「开始服务」-> 调 startService；
 * 5. UI-M1：三个分组各有自己的空状态文案、切换分组重新请求、
 *    接口 500 显示后端原话 + 重试按钮（且**不**同时显示空状态）。
 */
import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import OrdersView from "@/views/OrdersView.vue";
import { ApiError } from "@oto/shared/api";

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
    // 地址：列表里也要显示（师傅在路上就得看地址）
    address_region: "北京市朝阳区",
    address_detail: "建国路 88 号",
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

  it("订单卡片显示订单号 / 服务项 / 地址 / 时间 / 金额 / 状态", async () => {
    const { pinia, router } = await setupApp("/orders");

    const wrapper = mount(OrdersView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    const item = wrapper.findAll('[data-test="order-item"]')[0];
    expect(item.find('[data-test="order-no"]').text()).toContain(
      "OTO20260101000001",
    );
    expect(item.find('[data-test="order-item-name"]').text()).toContain("日常保洁");
    expect(item.find('[data-test="order-address"]').text()).toContain(
      "北京市朝阳区",
    );
    expect(item.find('[data-test="order-address"]').text()).toContain("建国路 88 号");
    expect(item.find('[data-test="order-time"]').text()).toContain("2026-01-01");
    expect(item.find('[data-test="order-amount"]').text()).toContain("99.00");
    expect(item.find('[data-test="order-status"]').text()).toContain("待接单");
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

  // ===================================================================
  // UI-M1：三种页面状态（骨架屏 / 出错 / 空数据）
  // ===================================================================

  it("请求中显示骨架屏", async () => {
    // 手动控制 resolve：请求不返回，骨架屏就该一直在
    let release: (value: unknown) => void = () => {};
    mockClient.listMasterOrders.mockImplementation(
      () =>
        new Promise((resolve) => {
          release = resolve;
        }),
    );

    const { pinia, router } = await setupApp("/orders");
    const wrapper = mount(OrdersView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    expect(wrapper.find('[data-test="skeleton"]').exists()).toBe(true);
    // 骨架屏期间不该同时冒出空状态或错误
    expect(wrapper.find('[data-test="empty-PENDING_ACCEPT"]').exists()).toBe(false);

    release({ items: [], total: 0, limit: 20, offset: 0 });
    await flushPromises();

    expect(wrapper.find('[data-test="skeleton"]').exists()).toBe(false);
  });

  it("三个分组空数据各显示自己的空状态", async () => {
    mockClient.listMasterOrders.mockResolvedValue({
      items: [],
      total: 0,
      limit: 20,
      offset: 0,
    });

    const { pinia, router } = await setupApp("/orders");
    const wrapper = mount(OrdersView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    // 第一个分组：待接单
    expect(wrapper.find('[data-test="empty-PENDING_ACCEPT"]').text()).toContain(
      "暂无待接单",
    );

    // 切到第二个分组：待服务
    await wrapper.findAll(".van-tab")[1].trigger("click");
    await vi.waitFor(() => {
      expect(wrapper.find('[data-test="empty-ACCEPTED"]').exists()).toBe(true);
    });
    expect(wrapper.find('[data-test="empty-ACCEPTED"]').text()).toContain("暂无待服务");

    // 切到第三个分组：服务中
    await wrapper.findAll(".van-tab")[2].trigger("click");
    await vi.waitFor(() => {
      expect(wrapper.find('[data-test="empty-IN_SERVICE"]').exists()).toBe(true);
    });
    expect(wrapper.find('[data-test="empty-IN_SERVICE"]').text()).toContain("暂无服务中");
  });

  it("切换分组触发重新请求（按新分组的状态拉）", async () => {
    const { pinia, router } = await setupApp("/orders");
    const wrapper = mount(OrdersView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    expect(mockClient.listMasterOrders).toHaveBeenCalledTimes(1);
    expect(mockClient.listMasterOrders).toHaveBeenLastCalledWith({
      status: "PENDING_ACCEPT",
    });

    await wrapper.findAll(".van-tab")[1].trigger("click");
    await vi.waitFor(() => {
      expect(mockClient.listMasterOrders).toHaveBeenLastCalledWith({
        status: "ACCEPTED",
      });
    });

    await wrapper.findAll(".van-tab")[2].trigger("click");
    await vi.waitFor(() => {
      expect(mockClient.listMasterOrders).toHaveBeenLastCalledWith({
        status: "IN_SERVICE",
      });
    });
  });

  it("接口 500 -> 显示后端原话 + 重试按钮（不白屏、也不显示空状态）", async () => {
    mockClient.listMasterOrders.mockRejectedValue(
      new ApiError(500, "服务器开小差了，请稍后再试", null),
    );

    const { pinia, router } = await setupApp("/orders");
    const wrapper = mount(OrdersView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    // 显示后端给的原话
    expect(wrapper.find('[data-test="error"]').text()).toBe("服务器开小差了，请稍后再试");
    // 有重试按钮
    expect(wrapper.find('[data-test="retry"]').exists()).toBe(true);
    // 出错时不该再显示空状态（否则「拉挂了」和「没单」看起来一样）
    expect(wrapper.find('[data-test="empty-PENDING_ACCEPT"]').exists()).toBe(false);
  });

  it("点重试 -> 重新请求 -> 请求成功后正常显示", async () => {
    mockClient.listMasterOrders.mockRejectedValueOnce(
      new ApiError(500, "服务器开小差了，请稍后再试", null),
    );

    const { pinia, router } = await setupApp("/orders");
    const wrapper = mount(OrdersView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    expect(wrapper.find('[data-test="retry"]').exists()).toBe(true);
    const callsBefore = mockClient.listMasterOrders.mock.calls.length;

    await wrapper.find('[data-test="retry"]').trigger("click");
    await flushPromises();

    expect(mockClient.listMasterOrders.mock.calls.length).toBe(callsBefore + 1);
    // 重试成功：错误提示撤掉，列表回来了
    expect(wrapper.find('[data-test="error"]').exists()).toBe(false);
    expect(wrapper.findAll('[data-test="order-item"]')).toHaveLength(2);
  });
});
