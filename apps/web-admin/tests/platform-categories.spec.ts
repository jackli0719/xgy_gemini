/**
 * 平台侧品类管理页的测试（/platform/categories）。
 *
 * 必测点：
 *
 * 1. **品类树 + 服务项列表**：树里出得去品类名；点一个品类，
 *    右边列得出这个品类下的服务项；
 * 2. **新建品类**：点「新建品类」-> 填表 -> 调 createPlatformCategory，
 *    参数正确；成功后**刷新列表**；
 * 3. **改价带 expected_status**：编辑服务项改价时，把「我以为的旧状态」
 *    一并带上（乐观锁）——服务端发现状态变了就返回 409。
 */
import { flushPromises, mount, type DOMWrapper } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ElTree } from "element-plus";

import PlatformCategoriesView from "@/views/PlatformCategoriesView.vue";
import type { CurrentUser } from "@/stores/session";

import { mockClient } from "./client-mock";
import { setupApp } from "./helpers";

vi.mock("@oto/shared/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@oto/shared/api")>();
  const { mockClient: client } = await import("./client-mock");
  return { ...actual, createApiClient: () => client };
});

const CATEGORY = {
  id: 11,
  name: "家庭保洁",
  parent_id: null,
  sort_order: 1,
  status: "ACTIVE",
  items: [
    {
      id: 21,
      category_id: 11,
      name: "日常保洁",
      base_price: "100.00",
      duration_min: 60,
      status: "ACTIVE",
      created_at: "2026-01-01T10:00:00Z",
    },
  ],
  children: [
    {
      id: 12,
      name: "深度保洁",
      parent_id: 11,
      sort_order: 2,
      status: "ACTIVE",
      items: [],
      children: [],
    },
  ],
};

const TREE = [CATEGORY];

/** 平台管理员（平台侧页面只有平台角色能进）。 */
const PLATFORM_ADMIN = {
  id: 1,
  nickname: "平台管理员",
  phone: "13700000001",
  role: "PLATFORM_ADMIN",
  provider_id: null,
};

async function mountPlatformPage(currentUser: CurrentUser = PLATFORM_ADMIN) {
  const { pinia } = await setupApp("/platform/categories", { currentUser });
  const wrapper = mount(PlatformCategoriesView, {
    global: { plugins: [pinia] },
  });
  await flushPromises();
  return { wrapper };
}

/** 点树上的一个节点（el-tree 的 node-click 是组件事件，测试里直接发）。 */
async function clickTreeNode(
  wrapper: { find: (selector: string) => DOMWrapper<Element> },
  node: unknown,
) {
  const tree = wrapper
    .find('[data-test="category-tree"]')
    .findComponent(ElTree);
  // el-tree 的 node-click 带四个参数（数据、节点、组件实例、事件对象），
  // 少传会触发组件的参数校验警告
  tree.vm.$emit("node-click", node, {}, {}, new Event("click"));
  await flushPromises();
}

describe("平台侧品类管理页", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    mockClient.listPlatformCategories.mockResolvedValue(TREE);
    mockClient.createPlatformCategory.mockResolvedValue({
      ...CATEGORY,
      id: 13,
      name: "月嫂服务",
      children: [],
    });
    mockClient.updatePlatformCategory.mockResolvedValue(CATEGORY);
    mockClient.createPlatformItem.mockResolvedValue({
      id: 22,
      category_id: 11,
      name: "开荒保洁",
      base_price: "260.00",
      duration_min: 180,
      status: "ACTIVE",
      created_at: "2026-01-04T10:00:00Z",
    });
    mockClient.updatePlatformItem.mockResolvedValue({
      ...CATEGORY.items[0],
      base_price: "150.50",
    });
  });

  it("品类树渲染：品类名与子品类都在", async () => {
    const { wrapper } = await mountPlatformPage();

    expect(mockClient.listPlatformCategories).toHaveBeenCalledTimes(1);
    const treeText = wrapper.find('[data-test="category-tree"]').text();
    expect(treeText).toContain("家庭保洁");
    expect(treeText).toContain("深度保洁");
  });

  it("选中品类后，右边列得出这个品类下的服务项", async () => {
    const { wrapper } = await mountPlatformPage();

    // 还没选：提示先选一个品类
    expect(wrapper.text()).toContain("请在左边选一个品类");

    await clickTreeNode(wrapper, {
      id: CATEGORY.id,
      label: CATEGORY.name,
      children: [],
      raw: CATEGORY,
    });

    expect(wrapper.text()).toContain("日常保洁");
    expect(wrapper.text()).toContain("100.00");
    expect(wrapper.findAll(".el-table__body-wrapper tbody tr")).toHaveLength(1);
  });

  it("新建品类：调 createPlatformCategory 参数正确，成功后刷新列表", async () => {
    const { wrapper } = await mountPlatformPage();
    expect(mockClient.listPlatformCategories).toHaveBeenCalledTimes(1);

    await wrapper.find('[data-test="create-category-btn"]').trigger("click");
    await flushPromises();
    expect(wrapper.find('[data-test="category-dialog"]').exists()).toBe(true);

    await wrapper.find('[data-test="category-name-field"] input').setValue("月嫂服务");
    await flushPromises();

    await wrapper.find('[data-test="submit-category-btn"]').trigger("click");
    await flushPromises();

    expect(mockClient.createPlatformCategory).toHaveBeenCalledTimes(1);
    expect(mockClient.createPlatformCategory).toHaveBeenCalledWith({
      name: "月嫂服务",
      parent_id: null,
      sort_order: 0,
    });
    // 表格里的数据以服务端为准：不刷新就会看到幽灵数据
    expect(mockClient.listPlatformCategories).toHaveBeenCalledTimes(2);
  });

  it("编辑服务项改价：调 updatePlatformItem，参数带 expected_status", async () => {
    const { wrapper } = await mountPlatformPage();

    await clickTreeNode(wrapper, {
      id: CATEGORY.id,
      label: CATEGORY.name,
      children: [],
      raw: CATEGORY,
    });

    await wrapper.findAll('[data-test="edit-item-btn"]')[0].trigger("click");
    await flushPromises();
    expect(wrapper.find('[data-test="item-dialog"]').exists()).toBe(true);

    await wrapper.find('[data-test="item-price-field"] input').setValue("150.50");
    await flushPromises();

    await wrapper.find('[data-test="submit-item-btn"]').trigger("click");
    await flushPromises();

    expect(mockClient.updatePlatformItem).toHaveBeenCalledTimes(1);
    expect(mockClient.updatePlatformItem).toHaveBeenCalledWith(
      { item_id: 21 },
      {
        name: "日常保洁",
        base_price: 150.5,
        duration_min: 60,
        status: "ACTIVE",
        // 乐观锁：把「我以为的旧状态」一并带上
        expected_status: "ACTIVE",
      },
    );
    expect(mockClient.listPlatformCategories).toHaveBeenCalledTimes(2);
  });
});
