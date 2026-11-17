/**
 * 必测 3（师傅管理页）：
 *
 * 1. **列表渲染**：mock 返回 3 个师傅，表格出 3 行；
 * 2. **状态切换**：点「停用」-> 调 PATCH，参数正确（{status: 'DISABLED'}）；
 * 3. **成功后刷新列表**（listProviderMasters 被调 2 次）。
 *
 * 另外钉一条边界：**前端不带 provider_id**——请求参数里只有师傅 id 和状态，
 * 归属由后端按 token 决定（卡片约束 1）。
 */
import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ProviderMastersView from "@/views/ProviderMastersView.vue";

import { mockClient } from "./client-mock";
import { setupApp } from "./helpers";

vi.mock("@oto/shared/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@oto/shared/api")>();
  const { mockClient: client } = await import("./client-mock");
  return { ...actual, createApiClient: () => client };
});

const MASTERS = {
  items: [
    {
      id: 201,
      real_name: "师傅甲",
      phone: "13800000005",
      rating: "4.5",
      status: "ACTIVE",
    },
    {
      id: 202,
      real_name: "师傅乙",
      phone: "13800000006",
      rating: null,
      status: "PENDING",
    },
    {
      id: 203,
      real_name: "师傅丙",
      phone: "13800000007",
      rating: "4.0",
      status: "DISABLED",
    },
  ],
  total: 3,
};

async function mountMastersPage() {
  const { pinia } = await setupApp("/provider/masters");
  const wrapper = mount(ProviderMastersView, {
    global: { plugins: [pinia] },
  });
  await flushPromises();
  return wrapper;
}

describe("师傅管理页", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    mockClient.listProviderMasters.mockResolvedValue(MASTERS);
    mockClient.updateProviderMaster.mockResolvedValue(MASTERS.items[0]);
  });

  it("列表渲染：三个师傅出三行", async () => {
    const wrapper = await mountMastersPage();

    const rows = wrapper.findAll(".el-table__body-wrapper tbody tr");
    expect(rows).toHaveLength(3);
    expect(wrapper.text()).toContain("师傅甲");
    expect(wrapper.text()).toContain("13800000005");
    expect(wrapper.text()).toContain("师傅丙");
  });

  it("状态切换：点停用调 PATCH，参数正确", async () => {
    const wrapper = await mountMastersPage();

    // 第一行是 ACTIVE 的师傅甲，按钮上写着「停用」
    const buttons = wrapper.findAll('[data-test="toggle-btn"]');
    expect(buttons[0].text()).toContain("停用");
    await buttons[0].trigger("click");
    await flushPromises();

    expect(mockClient.updateProviderMaster).toHaveBeenCalledTimes(1);
    expect(mockClient.updateProviderMaster).toHaveBeenCalledWith(
      { master_id: 201 },
      { status: "DISABLED" },
    );
  });

  it("停用成功后刷新列表", async () => {
    const wrapper = await mountMastersPage();
    expect(mockClient.listProviderMasters).toHaveBeenCalledTimes(1);

    await wrapper.findAll('[data-test="toggle-btn"]')[0].trigger("click");
    await flushPromises();

    expect(mockClient.updateProviderMaster).toHaveBeenCalledTimes(1);
    // 表格里的状态以服务端为准：不刷新就会看到幽灵状态
    expect(mockClient.listProviderMasters).toHaveBeenCalledTimes(2);
  });

  it("非在岗的师傅点「启用」改成 ACTIVE", async () => {
    const wrapper = await mountMastersPage();

    // 第三行是 DISABLED 的师傅丙，按钮上写着「启用」
    const buttons = wrapper.findAll('[data-test="toggle-btn"]');
    expect(buttons[2].text()).toContain("启用");
    await buttons[2].trigger("click");
    await flushPromises();

    expect(mockClient.updateProviderMaster).toHaveBeenCalledWith(
      { master_id: 203 },
      { status: "ACTIVE" },
    );
  });

  it("状态用不同颜色的标签显示", async () => {
    const wrapper = await mountMastersPage();

    // el-tag 的 type 决定颜色：class 里有 el-tag--success / --info / --danger
    const tags = wrapper.findAll(".el-tag");
    expect(tags).toHaveLength(3);
    expect(tags[0].text()).toContain("在岗");
    expect(tags[0].classes()).toContain("el-tag--success");
    expect(tags[1].text()).toContain("待审核");
    expect(tags[1].classes()).toContain("el-tag--info");
    expect(tags[2].text()).toContain("已停用");
    expect(tags[2].classes()).toContain("el-tag--danger");
  });

  it("改状态请求不带 provider_id：归属由后端按 token 决定", async () => {
    const wrapper = await mountMastersPage();

    await wrapper.findAll('[data-test="toggle-btn"]')[0].trigger("click");
    await flushPromises();

    const params = mockClient.updateProviderMaster.mock.calls[0][0];
    expect(params).toEqual({ master_id: 201 });
    expect(params).not.toHaveProperty("provider_id");
  });
});

describe("UI-03 师傅管理页打磨", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    mockClient.listProviderMasters.mockResolvedValue(MASTERS);
    mockClient.updateProviderMaster.mockResolvedValue(MASTERS.items[0]);
  });

  it("师傅列表为空时显示空状态，刷新按钮能再拉一次", async () => {
    mockClient.listProviderMasters.mockResolvedValue({ items: [], total: 0 });

    const wrapper = await mountMastersPage();

    expect(wrapper.find('[data-test="masters-empty"]').exists()).toBe(true);
    expect(wrapper.text()).toContain("暂无师傅");
    // 空的时候不摆一张空表
    expect(wrapper.find(".el-table").exists()).toBe(false);

    await wrapper.find('[data-test="masters-empty-refresh"]').trigger("click");
    await flushPromises();
    expect(mockClient.listProviderMasters).toHaveBeenCalledTimes(2);
  });

  it("状态切换中按钮显示 loading 并禁用，连点只改一次", async () => {
    // 改状态请求悬而未决：第一次还在途时点第二次，才测得到防连点。
    let resolveUpdate: (value: unknown) => void = () => {};
    mockClient.updateProviderMaster.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveUpdate = resolve;
        }),
    );

    const wrapper = await mountMastersPage();
    const button = wrapper.findAll('[data-test="toggle-btn"]')[0];

    // 真·连点：两次派发之间不 await（同一个 tick 内）
    await Promise.all([button.trigger("click"), button.trigger("click")]);
    await flushPromises();

    expect(mockClient.updateProviderMaster).toHaveBeenCalledTimes(1);
    // 在途期间：loading + 禁用
    const during = wrapper.findAll('[data-test="toggle-btn"]')[0];
    expect(during.classes()).toContain("is-loading");
    expect(during.attributes("disabled")).toBeDefined();

    resolveUpdate?.(MASTERS.items[0]);
    await flushPromises();
  });
});
