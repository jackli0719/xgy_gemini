/**
 * 必测 2：下单表单提交。
 *
 * mock client.placeOrder 成功 -> 跳转到 /orders。
 */
import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import OrderNewView from "@/views/OrderNewView.vue";

import { mockClient } from "./client-mock";
import { setupApp, waitForPath } from "./helpers";

vi.mock("@oto/shared/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@oto/shared/api")>();
  const { mockClient: client } = await import("./client-mock");
  return { ...actual, createApiClient: () => client };
});

const SLOT = {
  id: 20,
  item_id: 10,
  date: "2026-01-01",
  start_time: "09:00:00",
  end_time: "11:00:00",
  capacity: 3,
  used: 1,
  available: 2,
};

describe("下单页", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockClient.listItemSlots.mockResolvedValue([SLOT]);
    mockClient.placeOrder.mockResolvedValue({
      id: 1,
      order_no: "OTO2026010100001",
      status: "PENDING_PAY",
      amount: "99.00",
    });
  });

  it("提交下单成功后跳到 /orders", async () => {
    const { pinia, router } = await setupApp(
      "/order/new?itemId=10&slotId=20&itemName=日常保洁",
    );

    const wrapper = mount(OrderNewView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    await wrapper.find('[data-test="submit-order"]').trigger("click");
    await flushPromises();

    expect(mockClient.placeOrder).toHaveBeenCalledTimes(1);
    // 下单只传三个 id：金额由服务端算，前端不传
    expect(mockClient.placeOrder).toHaveBeenCalledWith({
      item_id: 10,
      slot_id: 20,
      address_id: 1,
    });
    await waitForPath(router, "/orders");
  });

  it("下拉里的地址会被带进下单请求", async () => {
    const { pinia, router } = await setupApp("/order/new?itemId=10&slotId=20");

    const wrapper = mount(OrderNewView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    // 地址下拉是占位数据，只有一个地址；点一下确认组件渲染出来了
    expect(wrapper.find('[data-test="address-select"]').exists()).toBe(true);

    await wrapper.find('[data-test="submit-order"]').trigger("click");
    await flushPromises();

    expect(mockClient.placeOrder).toHaveBeenCalledWith(
      expect.objectContaining({ address_id: 1 }),
    );
  });

  it("下单失败时留在本页并显示错误文案", async () => {
    mockClient.placeOrder.mockRejectedValue(new Error("时段已被约满"));

    const { pinia, router } = await setupApp("/order/new?itemId=10&slotId=20");
    const wrapper = mount(OrderNewView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    await wrapper.find('[data-test="submit-order"]').trigger("click");
    await flushPromises();

    expect(router.currentRoute.value.path).toBe("/order/new");
    expect(wrapper.find('[data-test="error"]').text()).toContain("时段已被约满");
  });
});
