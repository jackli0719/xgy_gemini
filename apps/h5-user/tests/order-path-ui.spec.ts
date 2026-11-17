/**
 * UI-01：用户下单路径的打磨（空状态 / 骨架屏 / 防连点）。
 *
 * 这里用 SDK 桩（client-mock）：页面调的还是 client.xxx，只是不发真请求。
 * 接口真出错的那条路径（500、网络中断）在 order-path-errors.spec.ts 里
 * 走真实 SDK + 桩 fetch 验。
 */
import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { shiftDate } from "@/utils/date";
import CatalogView from "@/views/CatalogView.vue";
import CategoryItemsView from "@/views/CategoryItemsView.vue";
import OrderNewView from "@/views/OrderNewView.vue";
import OrdersView from "@/views/OrdersView.vue";

import { mockClient } from "./client-mock";
import { setupApp, waitForPath } from "./helpers";

// 把 SDK 的 client 换成桩：页面调用的还是 client.listCategories，
// 只是不会真的发请求。
vi.mock("@oto/shared/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@oto/shared/api")>();
  const { mockClient: client } = await import("./client-mock");
  return { ...actual, createApiClient: () => client };
});

const CATEGORY = {
  id: 1,
  name: "家庭保洁",
  parent_id: null,
  sort_order: 1,
  children: [],
};

const ITEM = {
  id: 10,
  category_id: 1,
  name: "日常保洁",
  base_price: "99.00",
  duration_min: 120,
};

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

const ADDRESS = {
  id: 1,
  contact: "张三",
  phone: "13800000001",
  region: "北京",
  detail: "某街道 1 号",
};

describe("UI-01 用户下单路径", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockClient.listCategories.mockResolvedValue([CATEGORY]);
    mockClient.listCategoryItems.mockResolvedValue([ITEM]);
    mockClient.listItemSlots.mockResolvedValue([SLOT]);
    mockClient.getItem.mockResolvedValue(ITEM);
    mockClient.listAddresses.mockResolvedValue([ADDRESS]);
    mockClient.listMyOrders.mockResolvedValue({
      items: [],
      total: 0,
      limit: 20,
      offset: 0,
    });
    mockClient.placeOrder.mockResolvedValue({
      id: 1,
      order_no: "OTO2026010100001",
      status: "PENDING_PAY",
      amount: "99.00",
    });
  });

  // =================================================================
  // 必测 1：品类列表空数据 -> 显示空状态
  // =================================================================

  it("品类列表空数据时显示引导文案和按钮", async () => {
    mockClient.listCategories.mockResolvedValue([]);

    const { pinia, router } = await setupApp("/catalog");
    const wrapper = mount(CatalogView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    expect(wrapper.find('[data-test="empty"]').exists()).toBe(true);
    expect(wrapper.find('[data-test="empty-text"]').text()).toContain("服务品类");
    expect(wrapper.find('[data-test="empty-action"]').exists()).toBe(true);
    // 空状态下不该还挂着品类卡片
    expect(wrapper.findAll('[data-test="category-card"]')).toHaveLength(0);
  });

  it("订单列表空数据时显示空状态，按钮带去预约", async () => {
    const { pinia, router } = await setupApp("/orders");
    const wrapper = mount(OrdersView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    expect(wrapper.find('[data-test="empty"]').exists()).toBe(true);
    expect(wrapper.find('[data-test="empty-text"]').text()).toContain("还没有下过单");

    await wrapper.find('[data-test="empty-action"]').trigger("click");
    await waitForPath(router, "/catalog");
  });

  it("品类详情没有服务项时显示空状态，按钮回品类列表", async () => {
    mockClient.listCategoryItems.mockResolvedValue([]);

    const { pinia, router } = await setupApp("/catalog/1");
    const wrapper = mount(CategoryItemsView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    expect(wrapper.find('[data-test="empty"]').exists()).toBe(true);
    expect(wrapper.find('[data-test="empty-text"]').text()).toContain("服务项");

    await wrapper.find('[data-test="empty-action"]').trigger("click");
    await waitForPath(router, "/catalog");
  });

  it("下单页没有可约时段时给出「换一天」，并按新日期重新拉时段", async () => {
    mockClient.listItemSlots.mockResolvedValue([]);

    const { pinia, router } = await setupApp("/order/new?itemId=10&slotId=20");
    const wrapper = mount(OrderNewView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    expect(wrapper.find('[data-test="no-slot"]').exists()).toBe(true);

    await wrapper.find('[data-test="next-day"]').trigger("click");
    await flushPromises();

    const calls = mockClient.listItemSlots.mock.calls;
    expect(calls).toHaveLength(2);
    const firstDate = calls[0][0].date;
    expect(calls[1][0].date).toBe(shiftDate(firstDate, 1));
  });

  it("下单页没有地址时给出「去添加地址」按钮", async () => {
    mockClient.listAddresses.mockResolvedValue([]);

    const { pinia, router } = await setupApp("/order/new?itemId=10&slotId=20");
    const wrapper = mount(OrderNewView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    expect(wrapper.find('[data-test="no-address"]').exists()).toBe(true);
    expect(wrapper.find('[data-test="add-address"]').exists()).toBe(true);
  });

  // =================================================================
  // loading：请求中显示骨架屏
  // =================================================================

  it("请求没回来时显示骨架屏", async () => {
    // 一直不 resolve：页面停在「请求中」
    mockClient.listCategories.mockReturnValue(new Promise(() => {}));

    const { pinia, router } = await setupApp("/catalog");
    const wrapper = mount(CatalogView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    expect(wrapper.find('[data-test="skeleton"]').exists()).toBe(true);
    expect(wrapper.findAll('[data-test="category-card"]')).toHaveLength(0);
  });

  it("订单列表请求中显示骨架屏", async () => {
    mockClient.listMyOrders.mockReturnValue(new Promise(() => {}));

    const { pinia, router } = await setupApp("/orders");
    const wrapper = mount(OrdersView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    expect(wrapper.find('[data-test="skeleton"]').exists()).toBe(true);
    expect(wrapper.findAll('[data-test="order-item"]')).toHaveLength(0);
  });

  // =================================================================
  // 必测 2：下单提交中按钮禁用，连点两次只发一次
  // =================================================================

  it("提交中按钮禁用，连点两次只发一次下单请求", async () => {
    // 请求一直挂着：按钮保持 loading/disabled，连点的窗口才是真的
    mockClient.placeOrder.mockReturnValue(new Promise(() => {}));

    const { pinia, router } = await setupApp("/order/new?itemId=10&slotId=20");
    const wrapper = mount(OrderNewView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    const button = wrapper.find('[data-test="submit-order"]');
    // 两次点击之间**不 await**：真实用户连点就是同一个微任务里发生的，
    // 按钮的 disabled 还没来得及重新渲染。
    void button.trigger("click");
    void button.trigger("click");
    await flushPromises();

    expect(mockClient.placeOrder).toHaveBeenCalledTimes(1);
    // 提交中按钮是禁用的
    expect(wrapper.find('[data-test="submit-order"]').attributes("disabled")).toBeDefined();
  });

  it("下单失败后按钮恢复可用，可以再试一次", async () => {
    mockClient.placeOrder.mockRejectedValueOnce(new Error("时段已被约满"));

    const { pinia, router } = await setupApp("/order/new?itemId=10&slotId=20");
    const wrapper = mount(OrderNewView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    await wrapper.find('[data-test="submit-order"]').trigger("click");
    await flushPromises();

    expect(wrapper.find('[data-test="submit-order"]').attributes("disabled")).toBeUndefined();

    await wrapper.find('[data-test="submit-order"]').trigger("click");
    await flushPromises();

    expect(mockClient.placeOrder).toHaveBeenCalledTimes(2);
  });

  // =================================================================
  // 错误：不白屏，且能重试
  // =================================================================

  it("出错时显示错误文案和重试按钮，重试会重新请求", async () => {
    mockClient.listCategories.mockRejectedValue(new Error("品类加载失败"));

    const { pinia, router } = await setupApp("/catalog");
    const wrapper = mount(CatalogView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    expect(wrapper.find('[data-test="error"]').text()).toContain("品类加载失败");
    // 不白屏：页面标题还在，还能重试
    expect(wrapper.find(".page-title").exists()).toBe(true);

    mockClient.listCategories.mockResolvedValue([CATEGORY]);
    await wrapper.find('[data-test="retry"]').trigger("click");
    await flushPromises();

    expect(mockClient.listCategories).toHaveBeenCalledTimes(2);
    expect(wrapper.findAll('[data-test="category-card"]')).toHaveLength(1);
    expect(wrapper.find('[data-test="error"]').exists()).toBe(false);
  });
});
