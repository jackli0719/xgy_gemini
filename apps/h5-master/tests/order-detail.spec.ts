/**
 * 订单详情页（师傅端）。
 *
 * 顺手钉住：详情带客户联系方式与上门地址（师傅要上门），
 * 以及「按状态给按钮」——不该出现的按钮不出现。
 *
 * UI-M2 打磨的重点（这里每条都有一个用例钉着）：
 *
 * 1. **拒单成功 -> 跳回列表 + 提示「已拒单」**：
 *    后端拒单后把订单退回 PENDING_DISPATCH、清空 master_id，
 *    这单已经不属于师傅了，详情接口必然 404。
 *    所以拒单后**不能再刷新详情**，只能跳回列表（并显示一条回执）。
 * 2. **连点两次只发一次请求**：光靠 disabled 拦不住（两次点击之间
 *    Vue 还没 patch 出 disabled），必须有同步守卫。
 * 3. **动作失败不白屏**：显示后端原话 + 「返回列表」按钮，订单内容还在
 *    （拒单失败是个例外：后端原话显示在弹窗里，见第 11 条）。
 * 4. **按钮按状态给**：非当前状态不显示对应按钮。
 * 5. **动作成功后刷新详情**：接单 / 开工 / 完工成功都要重新拉一次详情，
 *    否则页面还按旧状态渲染按钮（接单后还挂着「接单 / 拒单」，
 *    师傅再点就是一次注定失败的请求）。
 * 6. **只有订单侧冲突（404）才刷新详情**：404 = 订单不存在 / 不是我的 /
 *    状态已变（后端同构），这时刷新才能拿到真实状态；
 *    409 = 师傅当前不可接单（停用 / 休假 / 未审核），订单状态压根没变，
 *    刷新学不到东西，所以不刷新；500 之类的普通失败同样不刷新。
 * 7. **刷新失败就不给动作按钮**：刷新失败 = 状态不可信，
 *    再给按钮等于给一个必然再撞一次 404 的死按钮。
 * 8. **首屏加载失败有「重试」**：不能逼用户退回列表再点进订单才能重试
 *    （列表页早就给了「重试」，两边要一致）。
 * 9. **两个错误源互斥**：动作错误与加载错误同时非空时（动作 404 → 刷新也 404），
 *    页面只能有一个「返回列表」按钮——两块都渲染就是两个，用户不知道该点哪个。
 * 10. **收尾失败说「操作已完成」**：动作成功了但收尾（跳回列表）挂了，
 *    报「操作失败」是骗人的——师傅会以为没拒成功、白点一次。
 * 11. **拒单失败弹窗不关**：原因保留、后端原话显示在弹窗里，
 *     师傅能直接再点一次「确认拒单」重试。
 * 12. **打开拒单弹窗先清掉上一次的错误**：弹窗里显示的是后端原话，
 *     带着上一次动作（比如接单失败）的错误打开弹窗，用户会以为
 *     这次拒单也失败了。
 */
import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import App from "@/App.vue";
import OrderDetailView from "@/views/OrderDetailView.vue";
import { setNotice, takeNotice } from "@/utils/notice";
import { ApiError } from "@oto/shared/api";

import { mockClient } from "./client-mock";
import { setupApp, waitForPath } from "./helpers";

vi.mock("@oto/shared/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@oto/shared/api")>();
  const { mockClient: client } = await import("./client-mock");
  return { ...actual, createApiClient: () => client };
});

function detail(
  status: "PENDING_ACCEPT" | "ACCEPTED" | "IN_SERVICE" | "PENDING_CONFIRM",
) {
  return {
    id: 1,
    order_no: "OTO20260101000001",
    status,
    amount: "99.00",
    item_id: 10,
    item_name: "日常保洁",
    slot_id: 3,
    slot_date: "2026-01-01",
    slot_start_time: "09:00:00",
    slot_end_time: "12:00:00",
    created_at: "2026-01-01T00:00:00Z",
    customer_contact: "张三",
    customer_phone: "13900000001",
    address_region: "北京市朝阳区",
    address_detail: "建国路 88 号",
  };
}

/** 空列表（列表页三个分组都用它）。 */
const EMPTY_LIST = { items: [], total: 0, limit: 20, offset: 0 };

describe("订单详情页（师傅端）", () => {
  beforeEach(() => {
    // reset（不是 clear）：还得把 mockOnce 的队列清掉，
    // 否则上一个用例没用完的一次性返回值会串到下一个用例。
    vi.resetAllMocks();
    // 回执是模块级单例，用例之间得清干净（否则提示会串到下一个用例）
    // setNotice("") = 写一条空回执 = 清空（生产代码没有单独的清空导出）
    setNotice("");
    mockClient.getMasterOrder.mockResolvedValue(detail("ACCEPTED"));
    mockClient.startService.mockResolvedValue({
      order_no: "OTO20260101000001",
      status: "IN_SERVICE",
      completed_at: null,
    });
    mockClient.listMasterOrders.mockResolvedValue(EMPTY_LIST);
    mockClient.getMasterProfile.mockResolvedValue({
      real_name: "张师傅",
      provider_name: "甲服务商",
      status: "ACTIVE",
      rating: "4.5",
    });
  });

  it("渲染订单信息与上门地址", async () => {
    const { pinia, router } = await setupApp("/orders/OTO20260101000001");

    const wrapper = mount(OrderDetailView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    expect(wrapper.find('[data-test="order-no"]').text()).toContain(
      "OTO20260101000001",
    );
    expect(wrapper.find('[data-test="customer"]').text()).toContain("张三");
    expect(wrapper.find('[data-test="address"]').text()).toContain("北京市朝阳区");
  });

  it("已接单的订单给「开始服务」按钮，点它调 startService", async () => {
    const { pinia, router } = await setupApp("/orders/OTO20260101000001");

    const wrapper = mount(OrderDetailView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    expect(wrapper.find('[data-test="start-button"]').exists()).toBe(true);
    expect(wrapper.find('[data-test="accept-button"]').exists()).toBe(false);

    await wrapper.find('[data-test="start-button"]').trigger("click");
    await flushPromises();

    expect(mockClient.startService).toHaveBeenCalledWith({
      order_no: "OTO20260101000001",
    });
  });

  it("待接单的订单给「接单 / 拒单」按钮", async () => {
    mockClient.getMasterOrder.mockResolvedValue(detail("PENDING_ACCEPT"));
    const { pinia, router } = await setupApp("/orders/OTO20260101000001");

    const wrapper = mount(OrderDetailView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    expect(wrapper.find('[data-test="accept-button"]').exists()).toBe(true);
    expect(wrapper.find('[data-test="reject-button"]').exists()).toBe(true);
    expect(wrapper.find('[data-test="start-button"]').exists()).toBe(false);
  });

  // ===================================================================
  // UI-M2：动作成功后刷新详情（按钮跟着新状态走）
  //
  // 这几条守的是**「成功后要重新拉详情」这条链**：
  // 把 accept / start 里的 act(..., load) 的第二个参数去掉，
  // 页面就会继续按旧状态渲染按钮（接单后还挂着「接单 / 拒单」），
  // 师傅再点一次就是注定失败的一次请求。
  //
  // 所以这里既断言「getMasterOrder 被调了第二次」，
  // 也断言「按钮已经换成新状态对应的那个」——少任何一半都钉不住这条链。
  // ===================================================================

  it("接单成功 -> 刷新详情，按钮跟着新状态走（不再显示「接单」）", async () => {
    // 第一次是首屏的 PENDING_ACCEPT，第二次是接单成功后刷新的 ACCEPTED
    mockClient.getMasterOrder
      .mockResolvedValueOnce(detail("PENDING_ACCEPT"))
      .mockResolvedValueOnce(detail("ACCEPTED"));
    mockClient.acceptOrder.mockResolvedValue({
      order_no: "OTO20260101000001",
      status: "ACCEPTED",
    });

    const { pinia, router } = await setupApp("/orders/OTO20260101000001");
    const wrapper = mount(OrderDetailView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    // 首屏是「接单 / 拒单」
    expect(wrapper.find('[data-test="accept-button"]').exists()).toBe(true);

    await wrapper.find('[data-test="accept-button"]').trigger("click");
    await flushPromises();

    // **确实刷新过**：初始 1 次 + 成功后刷新 1 次
    expect(mockClient.getMasterOrder).toHaveBeenCalledTimes(2);
    // 刷新后按钮跟着新状态走：PENDING_ACCEPT -> ACCEPTED = 「开始服务」
    expect(wrapper.find('[data-test="start-button"]').exists()).toBe(true);
    expect(wrapper.find('[data-test="accept-button"]').exists()).toBe(false);
  });

  it("开工成功 -> 刷新详情，按钮跟着新状态走（出现「完成服务」）", async () => {
    // 第一次是首屏的 ACCEPTED，第二次是开工成功后刷新的 IN_SERVICE
    mockClient.getMasterOrder
      .mockResolvedValueOnce(detail("ACCEPTED"))
      .mockResolvedValueOnce(detail("IN_SERVICE"));

    const { pinia, router } = await setupApp("/orders/OTO20260101000001");
    const wrapper = mount(OrderDetailView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    expect(wrapper.find('[data-test="start-button"]').exists()).toBe(true);

    await wrapper.find('[data-test="start-button"]').trigger("click");
    await flushPromises();

    // **确实刷新过**：初始 1 次 + 成功后刷新 1 次
    expect(mockClient.getMasterOrder).toHaveBeenCalledTimes(2);
    // 刷新后按钮跟着新状态走：ACCEPTED -> IN_SERVICE = 「完成服务」
    expect(wrapper.find('[data-test="finish-button"]').exists()).toBe(true);
    expect(wrapper.find('[data-test="start-button"]').exists()).toBe(false);
  });

  it("完工成功 -> 刷新详情，状态变「待确认」，动作按钮全部消失", async () => {
    // 第一次是首屏的 IN_SERVICE，第二次是完工成功后刷新的 PENDING_CONFIRM
    mockClient.getMasterOrder
      .mockResolvedValueOnce(detail("IN_SERVICE"))
      .mockResolvedValueOnce(detail("PENDING_CONFIRM"));
    mockClient.finishService.mockResolvedValue({
      order_no: "OTO20260101000001",
      status: "PENDING_CONFIRM",
      completed_at: null,
    });

    const { pinia, router } = await setupApp("/orders/OTO20260101000001");
    const wrapper = mount(OrderDetailView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    expect(wrapper.find('[data-test="finish-button"]').exists()).toBe(true);

    await wrapper.find('[data-test="finish-button"]').trigger("click");
    await flushPromises();

    // **确实刷新过**：初始 1 次 + 成功后刷新 1 次
    // （去掉 finish() 里的 act(..., load) 第二个参数，这里就会只剩 1 次）
    expect(mockClient.getMasterOrder).toHaveBeenCalledTimes(2);
    // 刷新后状态跟着新状态走：IN_SERVICE -> PENDING_CONFIRM = 「待确认」
    expect(wrapper.find('[data-test="order-status"]').text()).toContain("待确认");
    // 完工后订单进「待客户确认」，师傅这边**一个可点的动作都不剩**
    expect(wrapper.find('[data-test="finish-button"]').exists()).toBe(false);
    expect(wrapper.findAll(".page-footer button")).toHaveLength(0);
    // 不白屏：订单内容还在
    expect(wrapper.find('[data-test="order-no"]').exists()).toBe(true);
  });

  // ===================================================================
  // UI-M2：拒单后不回详情（详情必然 404）
  // ===================================================================

  it("拒单成功 -> 跳回列表并提示「已拒单」（不出现 404，也不刷新详情）", async () => {
    mockClient.getMasterOrder.mockResolvedValue(detail("PENDING_ACCEPT"));
    mockClient.rejectOrder.mockResolvedValue({
      order_no: "OTO20260101000001",
      status: "PENDING_DISPATCH",
      master_id: null,
    });

    // 挂整个应用：router-view 会真的渲染列表页，才能断言那条回执
    const { pinia, router } = await setupApp("/orders/OTO20260101000001");
    const wrapper = mount(App, { global: { plugins: [pinia, router] } });
    await vi.waitFor(() => {
      expect(wrapper.find('[data-test="reject-button"]').exists()).toBe(true);
    });

    const detailCallsBefore = mockClient.getMasterOrder.mock.calls.length;

    await wrapper.find('[data-test="reject-button"]').trigger("click");
    await flushPromises();
    await wrapper.find('[data-test="reject-reason"] input').setValue("临时有事");
    await wrapper.find('[data-test="reject-confirm"]').trigger("click");
    await flushPromises();

    await waitForPath(router, "/orders");
    await flushPromises();

    // 回到列表页
    expect(router.currentRoute.value.path).toBe("/orders");
    // 列表页顶部显示「已拒单」
    await vi.waitFor(() => {
      expect(wrapper.find('[data-test="notice"]').exists()).toBe(true);
    });
    expect(wrapper.find('[data-test="notice"]').text()).toContain("已拒单");

    // 没有 404 / 错误块（详情接口根本没再被调用，谈不上 404）
    expect(wrapper.find('[data-test="error"]').exists()).toBe(false);
    expect(wrapper.find('[data-test="action-error"]').exists()).toBe(false);
    expect(wrapper.find('[data-test="error-block"]').exists()).toBe(false);

    // **拒单后不能再拉详情**：这单已经不属于师傅了，拉了必然 404
    expect(mockClient.getMasterOrder.mock.calls.length).toBe(detailCallsBefore);
  });

  it("拒单失败 -> 留在详情页，弹窗不关、原因保留，后端原话显示在弹窗里", async () => {
    mockClient.getMasterOrder.mockResolvedValue(detail("PENDING_ACCEPT"));
    mockClient.rejectOrder.mockRejectedValue(
      new ApiError(500, "拒单失败，请稍后再试", null),
    );

    const { pinia, router } = await setupApp("/orders/OTO20260101000001");
    const wrapper = mount(OrderDetailView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    await wrapper.find('[data-test="reject-button"]').trigger("click");
    await flushPromises();
    await wrapper.find('[data-test="reject-reason"] input').setValue("临时有事");
    await wrapper.find('[data-test="reject-confirm"]').trigger("click");
    await flushPromises();

    // 还在详情页（没跳走）
    expect(router.currentRoute.value.path).toBe("/orders/OTO20260101000001");
    // **弹窗还开着**：失败就关掉的话，用户得重新打开、重填一遍原因
    // （RejectPopup 每次打开都清空输入）才知道成没成
    // 用 isVisible() 而不是 exists()：van-popup 关掉时只是 v-show 隐藏，
    // 节点还留在 DOM 里，exists() 照样为 true（那这条断言等于没钉）
    expect(wrapper.find('[data-test="reject-popup"]').isVisible()).toBe(true);
    // 后端原话显示在**弹窗里**（用户视线所在处），不在页面顶部
    expect(wrapper.find('[data-test="reject-server-error"]').isVisible()).toBe(
      true,
    );
    expect(wrapper.find('[data-test="reject-server-error"]').text()).toContain(
      "拒单失败，请稍后再试",
    );
    // 页面顶部不重复显示同一句话（弹窗里已经有一份）
    expect(wrapper.find('[data-test="action-error"]').exists()).toBe(false);
    // **原因没被清空**：可以直接再点「确认拒单」重试
    const reasonInput = wrapper.find(
      '[data-test="reject-reason"] input',
    ).element as HTMLInputElement;
    expect(reasonInput.value).toBe("临时有事");

    // 直接重试：原因还在，不用重填
    await wrapper.find('[data-test="reject-confirm"]').trigger("click");
    await flushPromises();
    expect(mockClient.rejectOrder).toHaveBeenCalledTimes(2);

    // 订单内容还在（不白屏）
    expect(wrapper.find('[data-test="order-no"]').exists()).toBe(true);
  });

  it("拒单失败后关掉弹窗 -> 页面顶部才给错误 + 返回列表按钮", async () => {
    mockClient.getMasterOrder.mockResolvedValue(detail("PENDING_ACCEPT"));
    mockClient.rejectOrder.mockRejectedValue(
      new ApiError(500, "拒单失败，请稍后再试", null),
    );

    const { pinia, router } = await setupApp("/orders/OTO20260101000001");
    const wrapper = mount(OrderDetailView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    await wrapper.find('[data-test="reject-button"]').trigger("click");
    await flushPromises();
    await wrapper.find('[data-test="reject-reason"] input').setValue("临时有事");
    await wrapper.find('[data-test="reject-confirm"]').trigger("click");
    await flushPromises();

    // 关掉弹窗（用户放弃重试）：错误回到页面顶部，用户有「返回列表」的出路
    await wrapper.find('[data-test="reject-cancel"]').trigger("click");
    await flushPromises();

    expect(wrapper.find('[data-test="action-error-text"]').text()).toContain(
      "拒单失败，请稍后再试",
    );
    expect(wrapper.find('[data-test="back-to-list"]').exists()).toBe(true);
  });

  it("打开拒单弹窗 -> 清掉上一次的错误（弹窗里不显示别人的错）", async () => {
    // 上一个动作（接单）失败，页面顶部有错误；再点「拒单」打开弹窗时，
    // 弹窗里**不能**还挂着那条错——用户会以为这次拒单也失败了。
    mockClient.getMasterOrder.mockResolvedValue(detail("PENDING_ACCEPT"));
    mockClient.acceptOrder.mockRejectedValue(
      new ApiError(409, "师傅当前不可接单：master_id=1", null),
    );

    const { pinia, router } = await setupApp("/orders/OTO20260101000001");
    const wrapper = mount(OrderDetailView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    // 先让接单失败，页面顶部挂上错误
    await wrapper.find('[data-test="accept-button"]').trigger("click");
    await flushPromises();
    expect(wrapper.find('[data-test="action-error-text"]').text()).toContain(
      "师傅当前不可接单",
    );

    // 打开拒单弹窗：上一次的错误被清掉
    await wrapper.find('[data-test="reject-button"]').trigger("click");
    await flushPromises();

    expect(wrapper.find('[data-test="reject-server-error"]').exists()).toBe(false);
    expect(wrapper.find('[data-test="action-error"]').exists()).toBe(false);
  });

  it("动作成功但收尾失败 -> 说「操作已完成」，不说「操作失败」", async () => {
    mockClient.getMasterOrder.mockResolvedValue(detail("PENDING_ACCEPT"));
    mockClient.rejectOrder.mockResolvedValue({
      order_no: "OTO20260101000001",
      status: "PENDING_DISPATCH",
      master_id: null,
    });

    const { pinia, router } = await setupApp("/orders/OTO20260101000001");
    // 收尾（跳回列表）挂了，但**动作本身是成功的**
    vi.spyOn(router, "replace").mockRejectedValue(new Error("导航失败"));

    const wrapper = mount(OrderDetailView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    await wrapper.find('[data-test="reject-button"]').trigger("click");
    await flushPromises();
    await wrapper.find('[data-test="reject-reason"] input').setValue("临时有事");
    await wrapper.find('[data-test="reject-confirm"]').trigger("click");
    await flushPromises();

    // 动作已经生效（后端把单退回 PENDING_DISPATCH），只是页面没跟上
    expect(mockClient.rejectOrder).toHaveBeenCalledTimes(1);
    const text = wrapper.find('[data-test="action-error-text"]').text();
    // **不能报「操作失败」**：那会让师傅以为没拒成功、白点一次
    expect(text).toContain("操作已完成");
    expect(text).not.toContain("操作失败");
    // 用户有出路：回列表
    expect(wrapper.find('[data-test="back-to-list"]').exists()).toBe(true);
  });

  // ===================================================================
  // UI-M2：防连点
  // ===================================================================

  it("连点两次「开始服务」只发一次请求", async () => {
    mockClient.getMasterOrder.mockResolvedValue(detail("ACCEPTED"));
    // 请求挂住不返回：好观察「在途」这个中间态
    let release: (value: unknown) => void = () => {};
    mockClient.startService.mockImplementation(
      () =>
        new Promise((resolve) => {
          release = resolve;
        }),
    );

    const { pinia, router } = await setupApp("/orders/OTO20260101000001");
    const wrapper = mount(OrderDetailView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    const button = wrapper.find('[data-test="start-button"]');
    // 两次点击**之间不 await**：真实场景就是用户连点，
    // 这时 Vue 还没 patch 出 disabled，第二次点击照样进得来。
    button.trigger("click");
    button.trigger("click");
    await flushPromises();

    expect(mockClient.startService).toHaveBeenCalledTimes(1);

    // 请求在途：按钮是 loading + disabled 的状态
    const pending = wrapper.find('[data-test="start-button"]');
    expect(pending.attributes("disabled")).toBeDefined();
    expect(pending.classes()).toContain("van-button--loading");

    release({
      order_no: "OTO20260101000001",
      status: "IN_SERVICE",
      completed_at: null,
    });
    await flushPromises();
  });

  // ===================================================================
  // UI-M2：动作失败不白屏
  // ===================================================================

  it("动作失败（404 订单侧冲突）-> 刷新详情，按钮跟着真实的新状态走", async () => {
    // **分两次返回不同状态**：第一次是页面初始的 ACCEPTED，
    // 第二次是冲突后刷新拿到的真实状态 IN_SERVICE。
    // 只回一个状态的话，刷新这个行为根本钉不住（按钮不会变），
    // 把 404 改成 418 用例也照样全绿。
    mockClient.getMasterOrder
      .mockResolvedValueOnce(detail("ACCEPTED"))
      .mockResolvedValueOnce(detail("IN_SERVICE"));
    mockClient.startService.mockRejectedValue(
      new ApiError(404, "订单不存在：order_no=OTO20260101000001", null),
    );

    const { pinia, router } = await setupApp("/orders/OTO20260101000001");
    const wrapper = mount(OrderDetailView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    await wrapper.find('[data-test="start-button"]').trigger("click");
    await flushPromises();

    // 后端原话
    expect(wrapper.find('[data-test="action-error-text"]').text()).toContain(
      "订单不存在",
    );
    // 「返回列表」按钮
    expect(wrapper.find('[data-test="back-to-list"]').exists()).toBe(true);
    expect(wrapper.find('[data-test="back-to-list"]').text()).toContain("返回列表");
    // 不白屏：订单内容还在
    expect(wrapper.find('[data-test="order-no"]').exists()).toBe(true);

    // **确实刷新过**：初始 1 次 + 冲突后刷新 1 次
    expect(mockClient.getMasterOrder).toHaveBeenCalledTimes(2);
    // 刷新成功后按钮跟着真实状态走：ACCEPTED -> IN_SERVICE = 「完成服务」
    expect(wrapper.find('[data-test="finish-button"]').exists()).toBe(true);
    expect(wrapper.find('[data-test="start-button"]').exists()).toBe(false);
  });

  it("动作失败（409 = 师傅当前不可接单）-> 显示后端原话，**不刷新详情**", async () => {
    // 后端契约：师傅端四个写接口里，**订单侧冲突一律是 404**；
    // 409 = MasterNotDispatchableError = 「师傅当前不可接单：master_id=N」
    // （停用 / 休假 / 未审核）——订单状态压根没变，
    // 刷新详情学不到任何东西，所以不刷新。
    mockClient.getMasterOrder.mockResolvedValue(detail("ACCEPTED"));
    mockClient.startService.mockRejectedValue(
      new ApiError(409, "师傅当前不可接单：master_id=1", null),
    );

    const { pinia, router } = await setupApp("/orders/OTO20260101000001");
    const wrapper = mount(OrderDetailView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    await wrapper.find('[data-test="start-button"]').trigger("click");
    await flushPromises();

    // 后端原话**原样显示**
    expect(wrapper.find('[data-test="action-error-text"]').text()).toContain(
      "师傅当前不可接单",
    );
    // 「返回列表」按钮（用户有出路）
    expect(wrapper.find('[data-test="back-to-list"]').exists()).toBe(true);
    // 不白屏：订单内容还在
    expect(wrapper.find('[data-test="order-no"]').exists()).toBe(true);
    // **不刷新**：409 跟订单状态无关，刷新只会白白多一次往返，
    // 还可能把「不可接单」这个真正的原因盖住。
    // 跟 404 / 500 两条用例一起，把三种分支的行为差异钉住。
    expect(mockClient.getMasterOrder).toHaveBeenCalledTimes(1);
    // **不因为 409 就藏掉动作按钮**：后端明确允许停用 / 休假的师傅拒单
    // （让他把手上的单退回去才是出路），藏掉按钮等于把单卡死在他手上。
    expect(wrapper.find('[data-test="start-button"]').exists()).toBe(true);
  });

  it("动作失败（500，不是订单侧冲突）-> 不刷新详情", async () => {
    mockClient.getMasterOrder.mockResolvedValue(detail("ACCEPTED"));
    mockClient.startService.mockRejectedValue(
      new ApiError(500, "服务器开小差了，请稍后再试", null),
    );

    const { pinia, router } = await setupApp("/orders/OTO20260101000001");
    const wrapper = mount(OrderDetailView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    await wrapper.find('[data-test="start-button"]').trigger("click");
    await flushPromises();

    // 后端原话
    expect(wrapper.find('[data-test="action-error-text"]').text()).toContain(
      "服务器开小差了",
    );
    // **500 不是订单侧冲突**：不刷新详情（只有初始那 1 次）。
    // 这条用例跟上面 404 / 409 两条一起，把三个分支的行为差异钉住。
    expect(mockClient.getMasterOrder).toHaveBeenCalledTimes(1);
  });

  it("动作失败（404）且刷新详情也 404 -> 不给动作按钮，内容不白屏", async () => {
    // 动作 404（订单不存在 / 不是我的单）之后会再拉一次详情，
    // 这次刷新也 404 -> 状态不可信 -> 死按钮不给。
    mockClient.getMasterOrder
      .mockResolvedValueOnce(detail("ACCEPTED"))
      .mockRejectedValueOnce(new ApiError(404, "订单不存在", null));
    mockClient.startService.mockRejectedValue(
      new ApiError(404, "订单不存在", null),
    );

    const { pinia, router } = await setupApp("/orders/OTO20260101000001");
    const wrapper = mount(OrderDetailView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    await wrapper.find('[data-test="start-button"]').trigger("click");
    await flushPromises();

    // 后端原话 + 返回列表按钮（用户有出路）
    expect(wrapper.find('[data-test="action-error-text"]').text()).toContain(
      "订单不存在",
    );
    expect(wrapper.find('[data-test="back-to-list"]').exists()).toBe(true);
    // **两个错误源互斥**：这里 actionError 与 loadError 同时非空
    // （动作 404 → 刷新详情也 404），两块都渲染就会出现**两个**
    // 「返回列表」按钮，用户不知道该点哪个
    expect(wrapper.findAll('[data-test="back-to-list"]')).toHaveLength(1);
    // **死按钮不给**：刷新失败了还挂「开始服务」，用户点了只会再撞一次 404
    expect(wrapper.find('[data-test="start-button"]').exists()).toBe(false);
    // 不白屏：订单内容还在
    expect(wrapper.find('[data-test="order-no"]').exists()).toBe(true);
  });

  it("详情接口 404（订单不存在）-> 显示后端原话 + 返回列表按钮", async () => {
    mockClient.getMasterOrder.mockRejectedValue(
      new ApiError(404, "订单不存在", null),
    );

    const { pinia, router } = await setupApp("/orders/OTO20260101000001");
    const wrapper = mount(OrderDetailView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    expect(wrapper.find('[data-test="error"]').text()).toContain("订单不存在");
    expect(wrapper.find('[data-test="back-to-list"]').exists()).toBe(true);
    expect(wrapper.find('[data-test="back-to-list"]').text()).toContain("返回列表");
    // 出错时不该同时冒出两个「返回列表」按钮
    expect(wrapper.findAll('[data-test="back-to-list"]')).toHaveLength(1);
  });

  it("详情首屏加载失败（网络异常）-> 给「重试」按钮，点它重新拉一次", async () => {
    // 第一次网络层失败，第二次成功：点「重试」要走同一条 load()。
    mockClient.getMasterOrder
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValueOnce(detail("ACCEPTED"));

    const { pinia, router } = await setupApp("/orders/OTO20260101000001");
    const wrapper = mount(OrderDetailView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    // 网络错的统一文案（见 utils/error.ts）
    expect(wrapper.find('[data-test="error"]').text()).toContain(
      "网络异常，请重试",
    );
    // **有「重试」**：不能逼用户退回列表再点进订单才能重试
    // （列表页早就有「重试」了，两边要一致）
    expect(wrapper.find('[data-test="retry"]').exists()).toBe(true);
    // 「返回列表」也留着（重试不是唯一出路）
    expect(wrapper.find('[data-test="back-to-list"]').exists()).toBe(true);

    await wrapper.find('[data-test="retry"]').trigger("click");
    await flushPromises();

    // 重试真的重新拉了一次详情
    expect(mockClient.getMasterOrder).toHaveBeenCalledTimes(2);
    // 成功后错误块消失，订单内容出来
    expect(wrapper.find('[data-test="error-block"]').exists()).toBe(false);
    expect(wrapper.find('[data-test="order-no"]').exists()).toBe(true);
  });

  // ===================================================================
  // UI-M2：按钮按订单状态给
  // ===================================================================

  it("非当前状态不显示对应按钮", async () => {
    // 已接单：只给「开始服务」
    mockClient.getMasterOrder.mockResolvedValue(detail("ACCEPTED"));
    let { pinia, router } = await setupApp("/orders/OTO20260101000001");
    let wrapper = mount(OrderDetailView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    expect(wrapper.find('[data-test="start-button"]').exists()).toBe(true);
    expect(wrapper.find('[data-test="accept-button"]').exists()).toBe(false);
    expect(wrapper.find('[data-test="reject-button"]').exists()).toBe(false);
    expect(wrapper.find('[data-test="finish-button"]').exists()).toBe(false);
    // 只给一组按钮，不多不少
    expect(wrapper.findAll(".page-footer button")).toHaveLength(1);

    // 待接单：只给「接单 / 拒单」
    mockClient.getMasterOrder.mockResolvedValue(detail("PENDING_ACCEPT"));
    ({ pinia, router } = await setupApp("/orders/OTO20260101000001"));
    wrapper = mount(OrderDetailView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    expect(wrapper.find('[data-test="accept-button"]').exists()).toBe(true);
    expect(wrapper.find('[data-test="reject-button"]').exists()).toBe(true);
    expect(wrapper.find('[data-test="start-button"]').exists()).toBe(false);
    expect(wrapper.find('[data-test="finish-button"]').exists()).toBe(false);
    expect(wrapper.findAll(".page-footer button")).toHaveLength(2);

    // 服务中：只给「完成服务」
    mockClient.getMasterOrder.mockResolvedValue(detail("IN_SERVICE"));
    ({ pinia, router } = await setupApp("/orders/OTO20260101000001"));
    wrapper = mount(OrderDetailView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    expect(wrapper.find('[data-test="finish-button"]').exists()).toBe(true);
    expect(wrapper.find('[data-test="start-button"]').exists()).toBe(false);
    expect(wrapper.find('[data-test="accept-button"]').exists()).toBe(false);
    expect(wrapper.find('[data-test="reject-button"]').exists()).toBe(false);
    expect(wrapper.findAll(".page-footer button")).toHaveLength(1);
  });

  // ===================================================================
  // UI-M2：回执只出现一次
  // ===================================================================

  it("回执只出现一次：takeNotice 读到即清空（消费后不再有残留）", () => {
    // beforeEach 已经 setNotice("") 复位了（写一条空回执 = 清空）
    setNotice("已拒单");
    // 第一次读到
    expect(takeNotice()).toBe("已拒单");
    // 第二次取不到 = 已经被消费掉，列表页不会看到残留
    expect(takeNotice()).toBe("");
  });
});
