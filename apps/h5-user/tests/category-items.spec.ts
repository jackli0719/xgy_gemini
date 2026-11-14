/**
 * 品类下的服务项页（卡片流程的第 2 步）。
 *
 * 钉住两件事：
 * - 拉的是「这个品类下的服务项」和「这些服务项当天的可约时段」；
 * - 点时段进下单页，并且带上正确的 itemId / slotId。
 */
import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import CategoryItemsView from "@/views/CategoryItemsView.vue";

import { mockClient } from "./client-mock";
import { setupApp, waitForPath } from "./helpers";

vi.mock("@oto/shared/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@oto/shared/api")>();
  const { mockClient: client } = await import("./client-mock");
  return { ...actual, createApiClient: () => client };
});

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

describe("品类服务项页", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockClient.listCategoryItems.mockResolvedValue([ITEM]);
    mockClient.listItemSlots.mockResolvedValue([SLOT]);
  });

  it("渲染服务项和它的可约时段", async () => {
    const { pinia, router } = await setupApp("/catalog/1");

    const wrapper = mount(CategoryItemsView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    expect(mockClient.listCategoryItems).toHaveBeenCalledWith({ category_id: 1 });
    expect(mockClient.listItemSlots).toHaveBeenCalledWith({
      item_id: 10,
      date: expect.any(String),
    });
    const cards = wrapper.findAll('[data-test="item-card"]');
    expect(cards).toHaveLength(1);
    expect(cards[0].text()).toContain("日常保洁");
    expect(wrapper.findAll('[data-test="slot-button"]')).toHaveLength(1);
  });

  it("点时段进下单页，带上 itemId 和 slotId", async () => {
    const { pinia, router } = await setupApp("/catalog/1");

    const wrapper = mount(CategoryItemsView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    await wrapper.find('[data-test="slot-button"]').trigger("click");
    await waitForPath(router, "/order/new");

    expect(router.currentRoute.value.query.itemId).toBe("10");
    expect(router.currentRoute.value.query.slotId).toBe("20");
  });
});
