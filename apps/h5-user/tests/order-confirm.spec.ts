/**
 * UI-02：用户「确认完成」这条路径。
 *
 * 盯四件事：
 * 1. 连点两次只发一次请求（同步 ref 守住，不只靠 disabled）；
 * 2. 确认成功后状态变 COMPLETED、按钮消失、显示完成时间；
 * 3. 确认 409（状态已变）显示提示并刷新最新状态，不白屏；
 * 4. 订单列表里 PENDING_CONFIRM 的行有醒目提示。
 *
 * 完成时间是**订单详情接口**给的（OrderDetail.completed_at，UI-02b 起）——
 * 页面直接读订单数据里的这个字段，不再从确认接口的响应里兜。
 */
import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@oto/shared/api";

import OrdersView from "@/views/OrdersView.vue";
import OrderDetailView from "@/views/OrderDetailView.vue";

import { mockClient } from "./client-mock";
import { setupApp } from "./helpers";

vi.mock("@oto/shared/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@oto/shared/api")>();
  const { mockClient: client } = await import("./client-mock");
  return { ...actual, createApiClient: () => client };
});

const ORDER_NO = "OTO2026010100001";

/** 完工时间（UTC）。业务时区是 Asia/Shanghai，所以显示成 2026-01-01 10:30。 */
const COMPLETED_AT = "2026-01-01T02:30:00Z";

function orderDetail(status: string, completedAt: string | null = null) {
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
    completed_at: completedAt,
  };
}

function orderListItem(orderNo: string, status: string) {
  return {
    order_no: orderNo,
    status,
    pay_status: "UNPAID",
    amount: "99.00",
    item_id: 10,
    item_name: "日常保洁",
    slot_date: "2026-01-01",
    slot_start_time: "09:00:00",
    created_at: "2026-01-01T00:00:00Z",
  };
}

/** 挂上详情页并等首屏数据到位。 */
async function mountDetail() {
  const { pinia, router } = await setupApp(`/orders/${ORDER_NO}`);
  const wrapper = mount(OrderDetailView, { global: { plugins: [pinia, router] } });
  await flushPromises();
  return wrapper;
}

describe("UI-02 确认完成", () => {
  beforeEach(() => {
    // reset 而不是 clear：clear 不清掉 mockResolvedValueOnce 排的队，
    // 上一条用例没消费掉的「下一次返回」会漏到这一条。
    vi.resetAllMocks();
    mockClient.getMyOrder.mockResolvedValue(orderDetail("PENDING_CONFIRM"));
    mockClient.confirmService.mockResolvedValue({
      order_no: ORDER_NO,
      status: "COMPLETED",
      completed_at: COMPLETED_AT,
    });
  });

  it("确认中按钮禁用，连点两次只发一次请求", async () => {
    // 确认请求悬而未决：第一次还在途时点第二次，才测得到防连点。
    let resolveConfirm: (value: unknown) => void = () => {};
    mockClient.confirmService.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveConfirm = resolve;
        }),
    );

    const wrapper = await mountDetail();
    const button = wrapper.find('[data-test="confirm-button"]');

    // 真·连点：两次派发之间不 await（同一个 tick 内），
    // 此时 DOM 上的 disabled 还没 patch 出来，第二次照样进得来 handler。
    const clicks = [button.trigger("click"), button.trigger("click")];
    await Promise.all(clicks);
    await flushPromises();

    expect(mockClient.confirmService).toHaveBeenCalledTimes(1);
    // 在途期间按钮是禁用的
    expect(wrapper.find('[data-test="confirm-button"]').attributes("disabled")).toBeDefined();

    resolveConfirm?.({
      order_no: ORDER_NO,
      status: "COMPLETED",
      completed_at: COMPLETED_AT,
    });
    await flushPromises();
  });

  it("确认成功后状态刷新为 COMPLETED，按钮消失并显示完成时间", async () => {
    // 第一次拿到待确认，确认后刷新拿到已完成（带完成时间）
    mockClient.getMyOrder
      .mockResolvedValueOnce(orderDetail("PENDING_CONFIRM"))
      .mockResolvedValue(orderDetail("COMPLETED", COMPLETED_AT));

    const wrapper = await mountDetail();
    await wrapper.find('[data-test="confirm-button"]').trigger("click");
    await flushPromises();

    expect(wrapper.find('[data-test="order-status"]').text()).toContain("已完成");
    expect(wrapper.find('[data-test="confirm-button"]').exists()).toBe(false);
    // 完成时间按业务时区显示（UTC 02:30 -> Asia/Shanghai 10:30）
    expect(wrapper.find('[data-test="completed-at"]').text()).toContain("2026-01-01 10:30");
  });

  it("确认 409（状态已变）时显示提示并刷新最新状态", async () => {
    mockClient.confirmService.mockRejectedValue(
      new ApiError(409, "订单当前状态不允许该操作", null),
    );
    mockClient.getMyOrder
      .mockResolvedValueOnce(orderDetail("PENDING_CONFIRM"))
      .mockResolvedValue(orderDetail("COMPLETED", COMPLETED_AT));

    const wrapper = await mountDetail();
    await wrapper.find('[data-test="confirm-button"]').trigger("click");
    await flushPromises();

    // 后端原话 + 「状态已变」的提示
    const message = wrapper.find('[data-test="confirm-error-text"]').text();
    expect(message).toContain("订单当前状态不允许该操作");
    expect(message).toContain("正在刷新最新状态");
    // 刷新了：详情重新拉了一次，拉回来的状态是已完成
    expect(mockClient.getMyOrder).toHaveBeenCalledTimes(2);
    expect(wrapper.find('[data-test="order-status"]').text()).toContain("已完成");
    expect(wrapper.find('[data-test="confirm-button"]').exists()).toBe(false);
    // 不白屏：订单内容还在
    expect(wrapper.find('[data-test="order-no"]').exists()).toBe(true);
  });

  it("确认成功但详情刷新失败时，状态仍是已完成（按钮不回来）", async () => {
    // 确认本身成功了，只是紧接着的详情刷新挂了。
    // 这时页面不能把按钮放回去让人再点一次——点了就是 409。
    mockClient.getMyOrder
      .mockResolvedValueOnce(orderDetail("PENDING_CONFIRM"))
      .mockRejectedValueOnce(new ApiError(500, "订单加载失败", null));

    const wrapper = await mountDetail();
    await wrapper.find('[data-test="confirm-button"]').trigger("click");
    await flushPromises();

    expect(wrapper.find('[data-test="order-status"]').text()).toContain("已完成");
    expect(wrapper.find('[data-test="confirm-button"]').exists()).toBe(false);
  });

  it("确认失败时显示后端原话并给出重试按钮，不白屏", async () => {
    mockClient.confirmService.mockRejectedValue(
      new ApiError(500, "服务暂时不可用，请稍后再试", null),
    );

    const wrapper = await mountDetail();
    await wrapper.find('[data-test="confirm-button"]').trigger("click");
    await flushPromises();

    expect(wrapper.find('[data-test="confirm-error-text"]').text()).toContain(
      "服务暂时不可用，请稍后再试",
    );
    expect(wrapper.find('[data-test="confirm-retry"]').exists()).toBe(true);
    // 不白屏：订单内容还在，确认按钮也还在（能重试）
    expect(wrapper.find('[data-test="order-no"]').exists()).toBe(true);
    expect(wrapper.find('[data-test="confirm-button"]').exists()).toBe(true);
  });

  it("直接打开已完成的订单就能看到完成时间（不靠确认接口的响应）", async () => {
    // 首屏就是已完成：详情接口自己带回 completed_at
    mockClient.getMyOrder.mockResolvedValue(orderDetail("COMPLETED", COMPLETED_AT));

    const wrapper = await mountDetail();

    expect(wrapper.find('[data-test="order-status"]').text()).toContain("已完成");
    expect(wrapper.find('[data-test="completed-at"]').text()).toContain("2026-01-01 10:30");
    // 早就完成、不是刚点完确认的：页面上一开始就有完成时间
    expect(mockClient.confirmService).not.toHaveBeenCalled();
  });

  it("没完成的订单不显示完成时间", async () => {
    mockClient.getMyOrder.mockResolvedValue(orderDetail("IN_SERVICE"));

    const wrapper = await mountDetail();

    expect(wrapper.find('[data-test="completed-at"]').exists()).toBe(false);
    // 订单内容照旧在页面上（没白屏）
    expect(wrapper.find('[data-test="order-no"]').exists()).toBe(true);
  });

  it("订单列表里待确认的行有醒目提示，其他状态没有", async () => {
    mockClient.listMyOrders.mockResolvedValue({
      items: [
        orderListItem("OTO2026010100001", "PENDING_CONFIRM"),
        orderListItem("OTO2026010100002", "IN_SERVICE"),
      ],
      total: 2,
      limit: 20,
      offset: 0,
    });

    const { pinia, router } = await setupApp("/orders");
    const wrapper = mount(OrdersView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    const items = wrapper.findAll('[data-test="order-item"]');
    expect(items[0].find('[data-test="pending-hint"]').text()).toContain("请确认");
    expect(items[1].find('[data-test="pending-hint"]').exists()).toBe(false);
  });
});
