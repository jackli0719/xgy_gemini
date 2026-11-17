/**
 * 必测 3（派单页）：
 *
 * 1. **派单列表渲染**：mock 返回 2 笔，表格出 2 行；
 * 2. **派单弹窗**：选师傅 -> 调 dispatch 接口，参数正确；
 * 3. **派单成功 -> 列表刷新**（listOrders 被调 2 次）。
 *
 * 另外钉一条边界：**前端不带 provider_id**——请求参数里只有状态和分页，
 * 归属由后端按 token 决定（卡片约束 1）。
 *
 * UI-03 追加盯四件事：
 * 1. 列表空 -> 显示空状态（一句人话 + 刷新按钮）；
 * 2. 没有在岗师傅 -> 提示「暂无在岗师傅」+ 确认按钮禁用；
 * 3. 连点两次只发一次请求（同步 ref 守住，不只靠 disabled）；
 * 4. 派单 409 / 404 -> 显示后端原话 + 刷新列表。
 */
import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@oto/shared/api";

import ProviderDispatchView from "@/views/ProviderDispatchView.vue";

import { mockClient } from "./client-mock";
import { setupApp } from "./helpers";

vi.mock("@oto/shared/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@oto/shared/api")>();
  const { mockClient: client } = await import("./client-mock");
  return { ...actual, createApiClient: () => client };
});

const ORDERS = {
  items: [
    {
      id: 101,
      order_no: "OTO20260101000001",
      status: "PENDING_DISPATCH",
      pay_status: "PAID",
      amount: "100.00",
      item_id: 5,
      item_name: "日常保洁",
      slot_date: "2026-01-02",
      slot_start_time: "09:00:00",
      created_at: "2026-01-01T10:00:00Z",
    },
    {
      id: 102,
      order_no: "OTO20260101000002",
      status: "PENDING_DISPATCH",
      pay_status: "PAID",
      amount: "200.00",
      item_id: 6,
      item_name: "深度保洁",
      slot_date: "2026-01-02",
      slot_start_time: "14:00:00",
      created_at: "2026-01-01T11:00:00Z",
    },
  ],
  total: 2,
  limit: 20,
  offset: 0,
};

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
      status: "ACTIVE",
    },
    // 已停用的师傅：后端派单会拒（409），所以下拉里不该出现
    {
      id: 203,
      real_name: "师傅丙",
      phone: "13800000007",
      rating: "4.0",
      status: "DISABLED",
    },
    // 还没通过审核的师傅：同样接不了单，也不该出现在下拉里
    {
      id: 204,
      real_name: "师傅丁",
      phone: "13800000008",
      rating: null,
      status: "PENDING",
    },
  ],
  total: 4,
};

async function mountDispatchPage() {
  const { pinia } = await setupApp("/provider/dispatch");
  const wrapper = mount(ProviderDispatchView, {
    global: { plugins: [pinia] },
  });
  await flushPromises();
  return wrapper;
}

/** 打开某行的派单弹窗、选中第 index 个师傅、确认派单。 */
async function dispatchTo(wrapper: Awaited<ReturnType<typeof mountDispatchPage>>, index: number) {
  await wrapper.findAll('[data-test="dispatch-btn"]')[0].trigger("click");
  await flushPromises();

  await wrapper.find('[data-test="master-select"] input').trigger("click");
  await flushPromises();

  const options = wrapper.findAll(".el-select-dropdown__item");
  await options[index].trigger("click");
  await flushPromises();

  await wrapper.find('[data-test="dispatch-confirm"]').trigger("click");
  await flushPromises();
}

describe("派单页", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    mockClient.listProviderOrders.mockResolvedValue(ORDERS);
    mockClient.listProviderMasters.mockResolvedValue(MASTERS);
    mockClient.dispatchOrder.mockResolvedValue({
      order_no: "OTO20260101000001",
      status: "PENDING_ACCEPT",
      master_id: 202,
    });
  });

  it("派单列表渲染：两笔订单出两行", async () => {
    const wrapper = await mountDispatchPage();

    const rows = wrapper.findAll(".el-table__body-wrapper tbody tr");
    expect(rows).toHaveLength(2);
    expect(wrapper.text()).toContain("OTO20260101000001");
    expect(wrapper.text()).toContain("OTO20260101000002");
  });

  it("列表请求不带 provider_id：归属由后端按 token 决定", async () => {
    await mountDispatchPage();

    expect(mockClient.listProviderOrders).toHaveBeenCalledTimes(1);
    const params = mockClient.listProviderOrders.mock.calls[0][0];
    expect(params).toEqual({ status: "PENDING_DISPATCH" });
    expect(params).not.toHaveProperty("provider_id");
  });

  it("派单弹窗：选师傅后调 dispatch 接口，参数正确", async () => {
    const wrapper = await mountDispatchPage();

    // 弹窗默认没开
    expect(wrapper.find('[data-test="dispatch-dialog"]').exists()).toBe(false);

    await wrapper.findAll('[data-test="dispatch-btn"]')[0].trigger("click");
    await flushPromises();
    expect(wrapper.find('[data-test="dispatch-dialog"]').exists()).toBe(true);

    // 选第二个师傅（师傅乙，id=202）
    await wrapper.find('[data-test="master-select"] input').trigger("click");
    await flushPromises();
    const options = wrapper.findAll(".el-select-dropdown__item");
    expect(options).toHaveLength(2);
    await options[1].trigger("click");
    await flushPromises();

    await wrapper.find('[data-test="dispatch-confirm"]').trigger("click");
    await flushPromises();

    expect(mockClient.dispatchOrder).toHaveBeenCalledTimes(1);
    // 第一行的订单 id 是 101，选中的师傅 id 是 202
    expect(mockClient.dispatchOrder).toHaveBeenCalledWith(
      { order_id: 101 },
      { master_id: 202 },
    );
  });

  it("派单成功后刷新列表（listOrders 被调 2 次）", async () => {
    const wrapper = await mountDispatchPage();
    expect(mockClient.listProviderOrders).toHaveBeenCalledTimes(1);

    await dispatchTo(wrapper, 1);

    expect(mockClient.dispatchOrder).toHaveBeenCalledTimes(1);
    // 派出去的订单已经不在待派单池里：不刷新就会看到幽灵数据
    expect(mockClient.listProviderOrders).toHaveBeenCalledTimes(2);
  });

  it("下拉只列在岗的师傅：接口返回 4 个，下拉只有 2 项", async () => {
    const wrapper = await mountDispatchPage();

    await wrapper.find('[data-test="dispatch-btn"]').trigger("click");
    await flushPromises();

    await wrapper.find('[data-test="master-select"] input').trigger("click");
    await flushPromises();

    // 接口返回了 4 个师傅（2 个在岗 + 1 个停用 + 1 个未审核），下拉里只有两个
    expect(mockClient.listProviderMasters).toHaveBeenCalledTimes(1);
    const options = wrapper.findAll(".el-select-dropdown__item");
    expect(options).toHaveLength(2);

    const labels = options.map((option) => option.text()).join();
    expect(labels).toContain("师傅甲");
    expect(labels).toContain("师傅乙");
    // 停用 / 未审核的师傅不该出现：派单会被后端拒掉（409）
    expect(labels).not.toContain("师傅丙");
    expect(labels).not.toContain("师傅丁");
  });
});

describe("UI-03 派单路径打磨", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    mockClient.listProviderOrders.mockResolvedValue(ORDERS);
    mockClient.listProviderMasters.mockResolvedValue(MASTERS);
    mockClient.dispatchOrder.mockResolvedValue({
      order_no: "OTO20260101000001",
      status: "PENDING_ACCEPT",
      master_id: 202,
    });
  });

  it("待派单列表为空时显示空状态，刷新按钮能再拉一次", async () => {
    mockClient.listProviderOrders.mockResolvedValue({
      items: [],
      total: 0,
      limit: 20,
      offset: 0,
    });

    const wrapper = await mountDispatchPage();

    // 空状态：一句人话 + 刷新按钮
    expect(wrapper.find('[data-test="dispatch-empty"]').exists()).toBe(true);
    expect(wrapper.text()).toContain("暂无待派单订单");
    // 空的时候不摆一张空表
    expect(wrapper.find(".el-table").exists()).toBe(false);

    await wrapper.find('[data-test="dispatch-empty-refresh"]').trigger("click");
    await flushPromises();
    expect(mockClient.listProviderOrders).toHaveBeenCalledTimes(2);
  });

  it("没有在岗师傅时提示「暂无在岗师傅」，确认按钮禁用", async () => {
    // 只有一个已停用的师傅：下拉里没有可选的人
    mockClient.listProviderMasters.mockResolvedValue({
      items: [
        {
          id: 203,
          real_name: "师傅丙",
          phone: "13800000007",
          rating: "4.0",
          status: "DISABLED",
        },
      ],
      total: 1,
    });

    const wrapper = await mountDispatchPage();
    await wrapper.findAll('[data-test="dispatch-btn"]')[0].trigger("click");
    await flushPromises();

    expect(wrapper.find('[data-test="no-master-hint"]').text()).toContain("暂无在岗师傅");
    // 没有人可派：确认按钮点下去也只会吃一个 409，直接禁掉
    expect(wrapper.find('[data-test="dispatch-confirm"]').attributes("disabled")).toBeDefined();
    expect(mockClient.dispatchOrder).not.toHaveBeenCalled();
  });

  it("派单提交中连点两次只发一次请求", async () => {
    // 派单请求悬而未决：第一次还在途时点第二次，才测得到防连点。
    let resolveDispatch: (value: unknown) => void = () => {};
    mockClient.dispatchOrder.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveDispatch = resolve;
        }),
    );

    const wrapper = await mountDispatchPage();

    // 先选师傅（选不了就没法派）
    await wrapper.findAll('[data-test="dispatch-btn"]')[0].trigger("click");
    await flushPromises();
    await wrapper.find('[data-test="master-select"] input').trigger("click");
    await flushPromises();
    await wrapper.findAll(".el-select-dropdown__item")[1].trigger("click");
    await flushPromises();

    // 真·连点：两次派发之间不 await（同一个 tick 内），
    // 此时 DOM 上的 disabled 还没 patch 出来，第二次照样进得来 handler。
    const button = wrapper.find('[data-test="dispatch-confirm"]');
    await Promise.all([button.trigger("click"), button.trigger("click")]);
    await flushPromises();

    expect(mockClient.dispatchOrder).toHaveBeenCalledTimes(1);
    // 在途期间按钮是禁用的
    expect(wrapper.find('[data-test="dispatch-confirm"]').attributes("disabled")).toBeDefined();

    resolveDispatch?.({
      order_no: "OTO20260101000001",
      status: "PENDING_ACCEPT",
      master_id: 202,
    });
    await flushPromises();
  });

  it("派单 409（订单已被派走）时显示后端原话并刷新列表", async () => {
    mockClient.dispatchOrder.mockRejectedValue(
      new ApiError(409, "订单已派单，不能重复派单：order_id=101", null),
    );

    const wrapper = await mountDispatchPage();
    await dispatchTo(wrapper, 1);

    // 后端原话，不换成自己的文案
    expect(wrapper.find('[data-test="dispatch-error"]').text()).toContain(
      "订单已派单，不能重复派单",
    );
    // 刷新了列表：409 意味着这行已经不是待派单了，页面上的列表过期了
    expect(mockClient.listProviderOrders).toHaveBeenCalledTimes(2);
    // 弹窗不关：换个师傅还能再试
    expect(wrapper.find('[data-test="dispatch-dialog"]').exists()).toBe(true);
  });

  it("派单 404（师傅不存在）时显示后端原话并刷新列表", async () => {
    mockClient.dispatchOrder.mockRejectedValue(
      new ApiError(404, "师傅不存在：master_id=202", null),
    );

    const wrapper = await mountDispatchPage();
    await dispatchTo(wrapper, 1);

    expect(wrapper.find('[data-test="dispatch-error"]').text()).toContain("师傅不存在");
    // 404 说明可选师傅列表也过期了，一样刷新
    expect(mockClient.listProviderOrders).toHaveBeenCalledTimes(2);
    expect(mockClient.listProviderMasters).toHaveBeenCalledTimes(2);
  });

  it("派单失败（500）显示后端原话，但不刷新列表", async () => {
    mockClient.dispatchOrder.mockRejectedValue(
      new ApiError(500, "服务暂时不可用，请稍后再试", null),
    );

    const wrapper = await mountDispatchPage();
    await dispatchTo(wrapper, 1);

    expect(wrapper.find('[data-test="dispatch-error"]').text()).toContain(
      "服务暂时不可用",
    );
    // 500 不是「列表过期」，刷新没有意义
    expect(mockClient.listProviderOrders).toHaveBeenCalledTimes(1);
  });
});
