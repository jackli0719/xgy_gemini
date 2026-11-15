/**
 * 必测 5：下单页的服务项名从接口拉。
 *
 * 顺带钉住另外两件事（FE-02b 已有，本卡换了数据来源，要重新确认）：
 * - 提交下单成功后跳到 /orders；
 * - 下拉里的地址会被带进下单请求（地址现在来自接口，不再是写死的占位）。
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

const ITEM = {
  id: 10,
  category_id: 1,
  name: "日常保洁",
  base_price: "99.00",
  duration_min: 120,
};

const ADDRESS = {
  id: 1,
  contact: "张三",
  phone: "13800000001",
  region: "北京",
  detail: "某街道 1 号",
};

describe("下单页", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockClient.listItemSlots.mockResolvedValue([SLOT]);
    mockClient.getItem.mockResolvedValue(ITEM);
    mockClient.listAddresses.mockResolvedValue([ADDRESS]);
    mockClient.placeOrder.mockResolvedValue({
      id: 1,
      order_no: "OTO2026010100001",
      status: "PENDING_PAY",
      amount: "99.00",
    });
  });

  it("商品名从接口拉，不靠 query 传", async () => {
    // query 里**故意**带一个错的商品名：页面上显示的必须是接口返回的那个
    const { pinia, router } = await setupApp(
      "/order/new?itemId=10&slotId=20&itemName=伪造的名称",
    );

    const wrapper = mount(OrderNewView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    expect(mockClient.getItem).toHaveBeenCalledWith({ item_id: 10 });
    expect(wrapper.find('[data-test="item-name"]').text()).toContain("日常保洁");
    expect(wrapper.text()).not.toContain("伪造的名称");
  });

  it("提交下单成功后跳到 /orders", async () => {
    const { pinia, router } = await setupApp("/order/new?itemId=10&slotId=20");

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

  it("地址从接口拉，下拉里的地址会被带进下单请求", async () => {
    const { pinia, router } = await setupApp("/order/new?itemId=10&slotId=20");

    const wrapper = mount(OrderNewView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    expect(mockClient.listAddresses).toHaveBeenCalledTimes(1);
    // 地址下拉是接口返回的数据
    expect(wrapper.find('[data-test="address-select"]').exists()).toBe(true);

    await wrapper.find('[data-test="submit-order"]').trigger("click");
    await flushPromises();

    expect(mockClient.placeOrder).toHaveBeenCalledWith(
      expect.objectContaining({ address_id: 1 }),
    );
  });

  it("没有地址时提示「请先添加地址」并挡住下单", async () => {
    mockClient.listAddresses.mockResolvedValue([]);

    const { pinia, router } = await setupApp("/order/new?itemId=10&slotId=20");
    const wrapper = mount(OrderNewView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    expect(wrapper.find('[data-test="no-address"]').text()).toContain("请先添加地址");

    await wrapper.find('[data-test="submit-order"]').trigger("click");
    await flushPromises();

    expect(mockClient.placeOrder).not.toHaveBeenCalled();
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
