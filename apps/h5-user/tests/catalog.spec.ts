/**
 * 必测 1：品类列表渲染。
 *
 * mock client.listCategories 返回 2 个品类 -> 页面出现 2 个卡片。
 */
import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import CatalogView from "@/views/CatalogView.vue";

import { mockClient } from "./client-mock";
import { setupApp, waitForPath } from "./helpers";

// 把 SDK 的 client 换成桩：页面调用的还是 client.listCategories，
// 只是不会真的发请求。
vi.mock("@oto/shared/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@oto/shared/api")>();
  const { mockClient: client } = await import("./client-mock");
  return { ...actual, createApiClient: () => client };
});

const TWO_CATEGORIES = [
  {
    id: 1,
    name: "家庭保洁",
    parent_id: null,
    sort_order: 1,
    children: [],
  },
  {
    id: 2,
    name: "深度保洁",
    parent_id: null,
    sort_order: 2,
    children: [],
  },
];

describe("品类列表页", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockClient.listCategories.mockResolvedValue(TWO_CATEGORIES);
  });

  it("渲染出 mock 返回的 2 个品类卡片", async () => {
    const { pinia, router } = await setupApp("/catalog");

    const wrapper = mount(CatalogView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    const cards = wrapper.findAll('[data-test="category-card"]');
    expect(cards).toHaveLength(2);
    expect(cards[0].text()).toContain("家庭保洁");
    expect(cards[1].text()).toContain("深度保洁");
    expect(mockClient.listCategories).toHaveBeenCalledTimes(1);
  });

  it("点卡片跳到该品类的服务项页", async () => {
    const { pinia, router } = await setupApp("/catalog");

    const wrapper = mount(CatalogView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    await wrapper.findAll('[data-test="category-card"]')[1].trigger("click");
    await waitForPath(router, "/catalog/2");
  });

  it("接口报错时显示错误文案，不渲染卡片", async () => {
    mockClient.listCategories.mockRejectedValue(new Error("品类加载失败"));

    const { pinia, router } = await setupApp("/catalog");
    const wrapper = mount(CatalogView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    expect(wrapper.find('[data-test="error"]').text()).toContain("品类加载失败");
    expect(wrapper.findAll('[data-test="category-card"]')).toHaveLength(0);
  });
});
