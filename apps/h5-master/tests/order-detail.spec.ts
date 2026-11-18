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
 * 13. **同一句错误只显示一次**：两个错误源互斥（v-if / v-else-if），
 *     actionError 与 loadError 同时非空时页面顶部只渲染一个块、
 *     只有一个「返回列表」；非 404 的拒单失败时弹窗开着，
 *     页面顶部**一个错误块都不渲染**（错误只在弹窗里出现一次）。
 * 14. **拒单请求在途**：真正发请求的是弹窗里的「确认拒单」按钮，
 *     它必须显示 loading + disabled（详情页上那个「拒单」按钮被弹窗
 *     挡住了，用户看不见它的 loading，会以为没点上）。
 * 15. **刷新不盖住内容 / 旧错误不挂着**：动作成功后的刷新在途时
 *     不出现加载动画（订单内容还在）；一次成功动作之后，
 *     上一次动作失败留下的错误被清掉。
 * 16. **拒单请求在途时关不掉弹窗**：请求已经发出去了，后端会把单真拒掉，
 *     这时候「取消」/ 遮罩关闭都**不是撤销**，只是把结果藏起来
 *     （用户以为取消了，实际单已经被拒 = 静默拒单）。
 * 17. **刷新详情失败要说「操作已完成」**：接单 / 开工 / 完工**已经成功**，
 *     只是随后的刷新挂了（比如这单已被收走 → GET 404）。
 *     这时报「操作失败」会让师傅以为没生效、再点一次、再撞一次 404。
 * 18. **遮罩关闭在请求结束后仍然有效**：请求在途时点过一次遮罩（被挡住），
 *     请求结束后再点遮罩，弹窗必须能正常关闭。Vant 内部的 opened 标志
 *     不能跟 show prop 失同步（失同步的话，遮罩那条路径在**本次打开期间**
 *     就永久失效了）。
 * 19. **空值校验错误不会赖着不走**：空着原因点了「确认拒单」会提示
 *     「请填写拒单原因」，但用户把原因填上之后那条错误就该消失——
 *     一条已经不成立的错误提示留着，会和后端原话并排显示；
 *     关掉弹窗再打开，也不该把上一次的校验错误带过来。
 * 20. **组件卸载后不再导航**：拒单请求在途时用户自己离开了详情页
 *     （后退 / 切到别的路由），请求回来后**不能**再把用户拽回订单列表——
 *     用户明明是自己走的。回执照写（单确实被拒了）。
 * 21. **404 的两种子情况都关弹窗**：404 = 订单侧冲突 = 这次动作
 *     **已经不适用了**（同一谓词、同一张单，再点一次只会再撞一次 404），
 *     所以刷新成功 / 刷新失败**一律关掉弹窗**。
 *     - 刷新成功（这单还在、只是状态变了）-> 页面顶部给后端原话
 *       + **刷新后的真实状态** + 「这次操作已不适用」
 *       （不然「订单不存在」跟同屏渲染的这单自相矛盾）。
 *     - 刷新失败（连这单都没了）-> 页面顶部给后端原话 + 「重新加载」
 *       + 「返回列表」（动作按钮不给：状态不可信）。
 *     非 404 的失败（500）则是弹窗留着、原地重试（见第 11 条）。
 * 22. **手动「重新加载」真的重拉一次详情**：动作 404 → 刷新也 404 →
 *     用户点「重新加载」→ 详情**真的被拉了第三次**（按钮是死的 / 无条件
 *     显示时，这条断言都会红）。
 * 23. **「重新加载」在途时按钮 disabled**：连点两次会并发发两次 GET；
 *     而且**在途的这几百毫秒里状态仍不可信**——旧状态的动作按钮
 *     不能冒出来（加载错误要等真的拉成功才清，见第 24 条）。
 * 24. **加载错误要等真的拉成功才清**：清早了的话，刷新在途的那一瞬间
 *     状态「看起来可信」，canAct 会把旧状态的动作按钮放出来，
 *     用户点一下就是注定失败的一次请求。
 * 25. **详情还在时没有「重新加载」**：动作失败而详情还在（409 / 500），
 *     重拉详情解决不了「这次动作被拒」，那种情况只给「返回列表」。
 * 26. **手动重试成功后旧横幅清掉**：页面状态已经更新成最新的了，
 *     顶部那句「订单不存在」还挂着就是自相矛盾。
 * 27. **首屏的「重试」在途时也 disabled**：连点两次会并发发两次 GET，
 *     后到的失败会把已经成功的加载盖掉（页面显示出订单、却一个动作按钮
 *     都没有——状态被写成了不可信）。
 */
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import App from "@/App.vue";
import RejectPopup from "@/components/RejectPopup.vue";
import { ORDER_STATUS_TEXT } from "@/constants/status";
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

/**
 * 拒单弹窗是不是**还开着**。
 *
 * **不能只看 isVisible()**：van-popup 靠 v-show 关（display:none 打在
 * 弹窗根节点上），而 VTU 的 isVisible() 在 jsdom 里**查不到祖先的
 * display:none** —— 弹窗已经关了它照样返回 true（实测过）。
 * 只用 isVisible() 断言「弹窗没被关掉」等于没断言。
 *
 * 所以这里看两样：show prop 还是 true，且弹窗根节点的 style 里
 * 没有 display:none。
 *
 * **元素不存在时要先判存在性**：van-popup 是 lazy render，弹窗**一次都
 * 没打开过**的时候根节点根本不在 DOM 里，find 返回空 wrapper，
 * 直接读 attributes() 会抛「Cannot call attributes on an empty DOMWrapper」
 * —— 而这里要的是「弹窗没开着 → false」，不是抛异常。
 */
function rejectPopupOpen(wrapper: VueWrapper): boolean {
  const popup = wrapper.findComponent(RejectPopup);
  const popupEl = wrapper.find(".van-popup");
  if (!popupEl.exists()) return false;
  const rootStyle = popupEl.attributes("style") ?? "";
  return popup.props("show") === true && !rootStyle.includes("display: none");
}

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

  it("拒单请求在途 -> 用户自己离开了详情页（组件卸载）-> 请求回来不再跳列表", async () => {
    // 拒单请求在途时用户按了后退 / 切到了别的路由：详情页组件被卸载了，
    // 但请求的续行照样会跑。这时候还去 `router.replace("/orders")`
    // = 把用户从他刚去的页面（比如「申请入驻」）硬拽回订单列表。
    //
    // 用户的直觉是「我自己走的，别拽我」。
    mockClient.getMasterOrder.mockResolvedValue(detail("PENDING_ACCEPT"));
    // 拒单请求挂住不返回：好观察「在途」这个中间态
    let release: (value: unknown) => void = () => {};
    mockClient.rejectOrder.mockImplementation(
      () =>
        new Promise((resolve) => {
          release = resolve;
        }),
    );
    // 用户会切到的那个页面（申请入驻）要用的接口
    mockClient.getMyOnboarding.mockRejectedValue(
      new ApiError(404, "还没有申请", null),
    );
    mockClient.listJoinableProviders.mockResolvedValue({ items: [] });

    // 挂整个应用：这样切路由时详情页组件才会真的被卸载。
    // 从列表页进详情（顺带把列表的 chunk 加载了：后面那条「导航回列表」
    // 的断言要能立刻看到路径变化，不能等懒加载）。
    const { pinia, router } = await setupApp("/orders");
    const wrapper = mount(App, { global: { plugins: [pinia, router] } });
    await waitForPath(router, "/orders");
    await router.push("/orders/OTO20260101000001");
    await waitForPath(router, "/orders/OTO20260101000001");
    await vi.waitFor(() => {
      expect(wrapper.find('[data-test="reject-button"]').exists()).toBe(true);
    });

    await wrapper.find('[data-test="reject-button"]').trigger("click");
    await flushPromises();
    await wrapper.find('[data-test="reject-reason"] input').setValue("临时有事");
    await wrapper.find('[data-test="reject-confirm"]').trigger("click");
    await flushPromises();
    expect(mockClient.rejectOrder).toHaveBeenCalledTimes(1);

    // **用户自己走了**：切到「申请入驻」-> 详情页组件被卸载
    await router.push("/onboard");
    await waitForPath(router, "/onboard");
    await flushPromises();
    expect(wrapper.find('[data-test="reject-button"]').exists()).toBe(false);

    // 从这里开始，任何导航都是「把用户拽走」——盯住它
    const pushSpy = vi.spyOn(router, "push");
    const replaceSpy = vi.spyOn(router, "replace");

    // 请求回来（后端确实把单拒了）
    release({
      order_no: "OTO20260101000001",
      status: "PENDING_DISPATCH",
      master_id: null,
    });
    await flushPromises();

    // **不能再把用户拽回订单列表**：他现在在 /onboard，就该留在 /onboard
    expect(router.currentRoute.value.path).toBe("/onboard");
    expect(replaceSpy).not.toHaveBeenCalled();
    expect(pushSpy).not.toHaveBeenCalled();
    // 回执照写：单确实被拒了，用户下次回列表会看到「已拒单」
    expect(takeNotice()).toBe("已拒单");
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
    // 用 rejectPopupOpen()（不是 exists()：van-popup 关掉时只是 v-show 隐藏，
    // 节点还留在 DOM 里，exists() 照样为 true，那这条断言等于没钉）
    expect(rejectPopupOpen(wrapper)).toBe(true);
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

  it("拒单请求在途 -> 弹窗里的「确认拒单」按钮显示 loading 并 disabled", async () => {
    // 拒单请求是**弹窗里的「确认拒单」按钮**发出的，
    // 所以「请求中」的反馈必须落在这个按钮上。
    // 详情页上那个「拒单」按钮的 loading 被弹窗挡住了，用户看不见，
    // 光靠它用户会以为没点上（连点虽然有 busy 守卫兜着，但用户不知道）。
    mockClient.getMasterOrder.mockResolvedValue(detail("PENDING_ACCEPT"));
    // 请求挂住不返回：好观察「在途」这个中间态
    let release: (value: unknown) => void = () => {};
    mockClient.rejectOrder.mockImplementation(
      () =>
        new Promise((resolve) => {
          release = resolve;
        }),
    );

    const { pinia, router } = await setupApp("/orders/OTO20260101000001");
    const wrapper = mount(OrderDetailView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    await wrapper.find('[data-test="reject-button"]').trigger("click");
    await flushPromises();
    await wrapper.find('[data-test="reject-reason"] input').setValue("临时有事");
    await wrapper.find('[data-test="reject-confirm"]').trigger("click");
    await flushPromises();

    expect(mockClient.rejectOrder).toHaveBeenCalledTimes(1);

    // 请求在途：弹窗里那个按钮是 loading + disabled 的状态
    // 用 isVisible() 不用 exists()：van-popup 用 v-show，
    // 关掉时节点还留在 DOM 里，exists() 照样为 true
    const confirmButton = wrapper.find('[data-test="reject-confirm"]');
    expect(confirmButton.isVisible()).toBe(true);
    expect(confirmButton.classes()).toContain("van-button--loading");
    expect(confirmButton.attributes("disabled")).toBeDefined();

    release({
      order_no: "OTO20260101000001",
      status: "PENDING_DISPATCH",
      master_id: null,
    });
    await flushPromises();
  });

  it("拒单请求在途 -> 「取消」点不动、弹窗关不掉（取消不是撤销）", async () => {
    // 请求发出后端就要把单拒掉。这时候用户点「取消」，弹窗是关了，
    // 但请求还在跑 —— 请求成功之后后端照样把单拒了，页面还会跳回列表
    // 显示「已拒单」。用户以为「取消 = 撤销」，实际单已经被拒了
    // （静默拒单，用户完全不知情）。
    //
    // 所以请求在途时「取消」必须 disabled，弹窗也关不掉。
    mockClient.getMasterOrder.mockResolvedValue(detail("PENDING_ACCEPT"));
    let release: (value: unknown) => void = () => {};
    mockClient.rejectOrder.mockImplementation(
      () =>
        new Promise((resolve) => {
          release = resolve;
        }),
    );

    const { pinia, router } = await setupApp("/orders/OTO20260101000001");
    const wrapper = mount(OrderDetailView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    await wrapper.find('[data-test="reject-button"]').trigger("click");
    await flushPromises();
    await wrapper.find('[data-test="reject-reason"] input').setValue("临时有事");
    await wrapper.find('[data-test="reject-confirm"]').trigger("click");
    await flushPromises();

    expect(mockClient.rejectOrder).toHaveBeenCalledTimes(1);

    // 请求在途：「取消」按钮不可点
    const cancelButton = wrapper.find('[data-test="reject-cancel"]');
    expect(cancelButton.attributes("disabled")).toBeDefined();

    // 点它：弹窗**不能**被关掉
    await cancelButton.trigger("click");
    await flushPromises();
    expect(rejectPopupOpen(wrapper)).toBe(true);

    // close() 自己也挡了一道（不只是 disabled 按钮）：
    // VTU 的 trigger 对 disabled 元素会**跳过派发**，所以这里直接调
    // close() —— 它在请求在途时必须什么都不做（少这一道，这条断言就废）。
    const popup = wrapper.findComponent(RejectPopup);
    const close = (popup.vm as unknown as { close: () => void }).close;
    close();
    await flushPromises();
    expect(rejectPopupOpen(wrapper)).toBe(true);

    // 遮罩那条关闭路径（van-popup 点遮罩也会要求关闭）同样关不掉：
    // 只挡按钮不挡遮罩，等于同一个坑留了另一个入口
    await wrapper.find(".van-overlay").trigger("click");
    await flushPromises();
    expect(rejectPopupOpen(wrapper)).toBe(true);

    // 收尾：把请求放出去（成功后弹窗自己关掉）
    release({
      order_no: "OTO20260101000001",
      status: "PENDING_DISPATCH",
      master_id: null,
    });
    await flushPromises();
  });

  it("被挡过一次遮罩后 -> 请求结束再点遮罩，弹窗仍能正常关闭", async () => {
    // 回归：以前「请求在途不许关弹窗」是**吞掉 update:show 事件**实现的。
    // 但 Vant 的 close() 是**先**把内部的 opened 置成 false、**再** emit
    // update:show(false)：emit 被吞掉 -> 父组件的 show 还是 true
    // （弹窗照常显示），可 Vant 内部的 opened 已经是 false 了。
    // 而 opened 只有在 show 由假变真时才会被 open() 重置 —— 于是
    // **本次打开期间遮罩那条关闭路径永久失效**：
    // 请求在途时点过一次遮罩（被挡住），等请求结束再点遮罩，弹窗纹丝不动。
    //
    // 现在改成 Vant 官方的 :close-on-click-overlay="!loading"：
    // 在途时 Vant 根本不进 close()（opened 保持 true），
    // 请求结束后遮罩又恢复正常关闭。
    mockClient.getMasterOrder.mockResolvedValue(detail("PENDING_ACCEPT"));
    // 请求挂住不返回（好观察「在途」这个中间态），结束后让它**失败**：
    // 失败时弹窗留着（用户要能直接重试），loading 变回 false。
    let fail: (err: unknown) => void = () => {};
    mockClient.rejectOrder.mockImplementation(
      () =>
        new Promise((_resolve, reject) => {
          fail = reject;
        }),
    );

    const { pinia, router } = await setupApp("/orders/OTO20260101000001");
    const wrapper = mount(OrderDetailView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    await wrapper.find('[data-test="reject-button"]').trigger("click");
    await flushPromises();
    await wrapper.find('[data-test="reject-reason"] input').setValue("临时有事");
    await wrapper.find('[data-test="reject-confirm"]').trigger("click");
    await flushPromises();

    // 请求在途：点遮罩被挡住，弹窗还开着
    await wrapper.find(".van-overlay").trigger("click");
    await flushPromises();
    expect(rejectPopupOpen(wrapper)).toBe(true);

    // 请求结束（失败 -> 弹窗留着重试，loading 变 false）
    fail(new ApiError(500, "拒单失败，请稍后再试", null));
    await flushPromises();
    expect(rejectPopupOpen(wrapper)).toBe(true);

    // **再点遮罩，弹窗能正常关闭**（这条就是回归点）
    await wrapper.find(".van-overlay").trigger("click");
    await flushPromises();
    expect(rejectPopupOpen(wrapper)).toBe(false);
    // 父组件的 show 也跟着变 false（不是只把 Vant 内部状态改了）
    expect(wrapper.findComponent(RejectPopup).props("show")).toBe(false);
  });

  it("弹窗一次都没打开过 -> rejectPopupOpen() 返回 false（不是抛异常）", async () => {
    // van-popup 是 lazy render：弹窗**一次都没打开过**的时候，
    // 它的根节点根本不在 DOM 里。测试辅助函数如果直接去读那个节点的
    // style，会抛「Cannot call attributes on an empty DOMWrapper」——
    // 判「弹窗开没开」这种事不该把用例整个炸掉。
    mockClient.getMasterOrder.mockResolvedValue(detail("PENDING_ACCEPT"));
    const { pinia, router } = await setupApp("/orders/OTO20260101000001");
    const wrapper = mount(OrderDetailView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    // 还没点过「拒单」，弹窗从没打开过：根节点不在 DOM 里
    expect(wrapper.find(".van-popup").exists()).toBe(false);
    expect(rejectPopupOpen(wrapper)).toBe(false);
  });

  it("空着原因点「确认拒单」-> 填上原因后那条校验错误就消失", async () => {
    // 空值校验错误一旦置位就再也不会清掉：用户先空着原因点了「确认拒单」
    // （弹出「请填写拒单原因」），再填上原因，那条错误还挂在弹窗里——
    // 一条已经不成立的错误提示，甚至会和后端原话并排显示。
    mockClient.getMasterOrder.mockResolvedValue(detail("PENDING_ACCEPT"));
    const { pinia, router } = await setupApp("/orders/OTO20260101000001");
    const wrapper = mount(OrderDetailView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    await wrapper.find('[data-test="reject-button"]').trigger("click");
    await flushPromises();

    // 不填原因就点确认：提示「请填写拒单原因」
    await wrapper.find('[data-test="reject-confirm"]').trigger("click");
    await flushPromises();
    expect(wrapper.find('[data-test="reject-error"]').text()).toContain(
      "请填写拒单原因",
    );

    // 原因填上了 → 那条校验错误不再成立 → 消失
    await wrapper.find('[data-test="reject-reason"] input').setValue("临时有事");
    await flushPromises();
    expect(wrapper.find('[data-test="reject-error"]').exists()).toBe(false);
  });

  it("空原因点过确认 -> 关掉再打开弹窗，那条校验错误不残留", async () => {
    // 弹窗每次打开都清空上一次的输入（免得把上一单的原因带给这一单），
    // 同理也该清掉上一次的「请填写拒单原因」——
    // 否则重新打开时还挂着一条已经不成立的错误。
    mockClient.getMasterOrder.mockResolvedValue(detail("PENDING_ACCEPT"));
    const { pinia, router } = await setupApp("/orders/OTO20260101000001");
    const wrapper = mount(OrderDetailView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    // 打开弹窗 -> 空着原因点确认 -> 出现校验错误
    await wrapper.find('[data-test="reject-button"]').trigger("click");
    await flushPromises();
    await wrapper.find('[data-test="reject-confirm"]').trigger("click");
    await flushPromises();
    expect(wrapper.find('[data-test="reject-error"]').exists()).toBe(true);

    // 关掉弹窗（取消），再打开
    await wrapper.find('[data-test="reject-cancel"]').trigger("click");
    await flushPromises();
    await wrapper.find('[data-test="reject-button"]').trigger("click");
    await flushPromises();

    // 重新打开时，那条校验错误不残留
    expect(wrapper.find('[data-test="reject-error"]').exists()).toBe(false);
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

  it("接单成功但刷新详情失败 -> 说「操作已完成」并带后端原话", async () => {
    // 接单**已经成功**（后端把单变成 ACCEPTED 了），只是随后的刷新详情挂了
    // （这单在刷新之前被收走 → GET 详情 404）。
    //
    // 这时候报「操作失败」是骗人的：师傅会以为刚才那一下没生效，
    // 可能再点一次、再撞一次 404（按钮已经因为 loadError 非空被藏了）。
    // 所以主句必须是「操作已完成」，同时把后端原话带上。
    mockClient.getMasterOrder
      .mockResolvedValueOnce(detail("PENDING_ACCEPT"))
      .mockRejectedValueOnce(
        new ApiError(404, "订单不存在：order_no=OTO20260101000001", null),
      );
    mockClient.acceptOrder.mockResolvedValue({
      order_no: "OTO20260101000001",
      status: "ACCEPTED",
    });

    const { pinia, router } = await setupApp("/orders/OTO20260101000001");
    const wrapper = mount(OrderDetailView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    await wrapper.find('[data-test="accept-button"]').trigger("click");
    await flushPromises();

    // 动作**已经成功**
    expect(mockClient.acceptOrder).toHaveBeenCalledTimes(1);
    // 刷新确实试过了（首屏 1 次 + 成功后刷新 1 次）
    expect(mockClient.getMasterOrder).toHaveBeenCalledTimes(2);

    const text = wrapper.find('[data-test="action-error-text"]').text();
    // **主句说「已完成」**：动作已经生效了，不能报「操作失败」
    expect(text).toContain("操作已完成");
    expect(text).not.toContain("操作失败");
    // **带上后端原话**（loadError 里就是它）：让师傅知道到底发生了什么
    expect(text).toContain("订单不存在");
    // 用户有出路：回列表
    expect(wrapper.find('[data-test="back-to-list"]').exists()).toBe(true);
    // 刷新失败 = 状态不可信 = 死按钮不给（canAct 因 loadError 非空而 false）
    expect(wrapper.find('[data-test="accept-button"]').exists()).toBe(false);
    // 不白屏：订单内容还在
    expect(wrapper.find('[data-test="order-no"]').exists()).toBe(true);
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
    // **详情还在（loadError 是空的）-> 错误块里没有「重新加载」**：
    // 重拉详情解决不了「这次动作被拒」，那种情况给「返回列表」就够了。
    // （把 v-if="loadError" 改成恒真的话，这里就会多出一个按钮。）
    expect(wrapper.find('[data-test="action-error"]').exists()).toBe(true);
    expect(wrapper.find('[data-test="retry"]').exists()).toBe(false);
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

  it("拒单 404 且刷新详情也 404 -> 关掉弹窗，页面顶部给后端原话 + 重新加载 + 返回列表", async () => {
    // 拒单返回 404（订单侧冲突）之后 act() 会再拉一次详情；
    // 这次刷新也 404 -> actionError 与 loadError 同时非空，
    // 而且是**同一句**后端原话（「订单不存在：order_no=…」）。
    //
    // **弹窗关掉**：404 = 这次动作已经不适用了（同一谓词、同一张单，
    // 再点一次「确认拒单」只会再撞一次 404）。页面上的动作按钮已经被
    // canAct 藏掉，弹窗里的按钮不该是唯一的例外。
    mockClient.getMasterOrder
      .mockResolvedValueOnce(detail("PENDING_ACCEPT"))
      .mockRejectedValueOnce(
        new ApiError(404, "订单不存在：order_no=OTO20260101000001", null),
      );
    mockClient.rejectOrder.mockRejectedValue(
      new ApiError(404, "订单不存在：order_no=OTO20260101000001", null),
    );

    const { pinia, router } = await setupApp("/orders/OTO20260101000001");
    const wrapper = mount(OrderDetailView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    await wrapper.find('[data-test="reject-button"]').trigger("click");
    await flushPromises();
    await wrapper.find('[data-test="reject-reason"] input').setValue("临时有事");
    await wrapper.find('[data-test="reject-confirm"]').trigger("click");
    await flushPromises();

    // **弹窗关掉了**：再点一次只会再撞一次注定失败的 404
    expect(rejectPopupOpen(wrapper)).toBe(false);

    // 页面顶部显示后端原话（两个错误源互斥，只显示一句）
    const text = wrapper.find('[data-test="action-error-text"]').text();
    expect(text).toContain("订单不存在");
    // **两个出路**：重新加载（重新拉一次详情）+ 返回列表，各一个
    // （两个错误块互斥，两块都渲染就是两个「返回列表」，用户不知道该点哪个）
    expect(wrapper.findAll('[data-test="retry"]')).toHaveLength(1);
    expect(wrapper.findAll('[data-test="back-to-list"]')).toHaveLength(1);
    // **死按钮不给**：刷新失败 = 状态不可信 = 点了也只会再撞一次 404
    expect(wrapper.find('[data-test="accept-button"]').exists()).toBe(false);
    expect(wrapper.find('[data-test="reject-button"]').exists()).toBe(false);
    // 不白屏：订单内容还在
    expect(wrapper.find('[data-test="order-no"]').exists()).toBe(true);

    // 点一下「重新加载」：**详情真的被拉了第三次**
    // （初始 1 次 + 404 分支刷新 1 次 + 手动重试 1 次）。
    // 只数按钮个数钉不住这个——按钮是死的、或者无条件显示，
    // 那个计数照样成立。
    await wrapper.find('[data-test="retry"]').trigger("click");
    await flushPromises();
    expect(mockClient.getMasterOrder).toHaveBeenCalledTimes(3);
    // 重新加载成功了：旧横幅（「订单不存在」）跟同屏渲染的订单自相矛盾，
    // 已经清掉（页面状态是最新的，不需要再提示失败）
    expect(wrapper.find('[data-test="action-error"]').exists()).toBe(false);
    expect(wrapper.find('[data-test="error-block"]').exists()).toBe(false);
    // 订单内容还在（不白屏）
    expect(wrapper.find('[data-test="order-no"]').exists()).toBe(true);
  });

  it("手动「重新加载」在途 -> 旧状态的动作按钮不给，按钮本身 disabled", async () => {
    // 动作 404 -> 刷新也 404 -> 状态不可信（loadError 非空）-> 动作按钮不给。
    // 用户点「重新加载」，**在途的那几百毫秒里**状态照样不可信：
    // 加载错误要等真的拉成功才清，所以旧状态的动作按钮不能冒出来。
    //
    // 如果 load() 一开头就把 loadError 清掉，这段时间里状态「看起来可信」，
    // 旧状态的「开始服务」会被放出来（而且**能点**）——用户点一下就是
    // 一次注定 404 的请求。这违反 canAct 自己的不变量。
    //
    // 同时钉住「在途时按钮不可点」：连点两次会并发发两次 GET。
    let release: (value: unknown) => void = () => {};
    mockClient.getMasterOrder
      .mockResolvedValueOnce(detail("ACCEPTED"))
      .mockRejectedValueOnce(new ApiError(404, "订单不存在", null))
      // 第三次（手动重新加载）挂住不返回：好观察「在途」这个中间态
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            release = resolve;
          }),
      );
    mockClient.startService.mockRejectedValue(
      new ApiError(404, "订单不存在", null),
    );

    const { pinia, router } = await setupApp("/orders/OTO20260101000001");
    const wrapper = mount(OrderDetailView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    await wrapper.find('[data-test="start-button"]').trigger("click");
    await flushPromises();

    // 刷新也 404：状态不可信，动作按钮不给
    expect(wrapper.find('[data-test="start-button"]').exists()).toBe(false);
    // 顶部给出「重新加载」（重新拉一次详情的出路）
    expect(wrapper.find('[data-test="retry"]').exists()).toBe(true);

    // 点「重新加载」：第三次请求在途
    await wrapper.find('[data-test="retry"]').trigger("click");
    await flushPromises();

    // **在途时状态仍不可信**：旧状态的动作按钮不给（也不能点）
    expect(wrapper.find('[data-test="start-button"]').exists()).toBe(false);
    // 按钮本身在途时不可点 + 显示 loading（连点不会并发发两次 GET）
    const pending = wrapper.find('[data-test="retry"]');
    expect(pending.attributes("disabled")).toBeDefined();
    expect(pending.classes()).toContain("van-button--loading");

    release(detail("ACCEPTED"));
    await flushPromises();
  });

  it("拒单 404 但刷新成功（这单还在，只是状态变了）-> 关掉弹窗，顶部给后端原话 + 现在的状态 + 已不适用", async () => {
    // 拒单返回 404 之后会再拉一次详情。**刷新成功**说明这单还在，
    // 只是**这次动作已经不适用了**（比如已经在另一端被接单了）。
    //
    // 这时候弹窗留着是个坑：
    // - 弹窗里挂着的「订单不存在」跟刚成功的刷新**自相矛盾**
    //   （页面背后已经显示「服务中」了）；
    // - 「确认拒单」还能点 -> 再发一次注定 404 的拒单 + 一次刷新，
    //   用户在无限无效循环里打转。
    //
    // 所以刷新成功也关掉弹窗，让用户回列表看最新状态。
    // 页面顶部那句文案必须**带上刷新后的真实状态**：光说「订单不存在」，
    // 跟同屏渲染的这单自相矛盾，用户不知道该信哪个。
    //
    // 刷新后的状态特意取 **IN_SERVICE**：取 ACCEPTED 的话，
    // 文案里硬编码成「已接单」也能蒙混过关（见下面的断言）。
    mockClient.getMasterOrder
      .mockResolvedValueOnce(detail("PENDING_ACCEPT"))
      .mockResolvedValueOnce(detail("IN_SERVICE"));
    mockClient.rejectOrder.mockRejectedValue(
      new ApiError(404, "订单不存在：order_no=OTO20260101000001", null),
    );

    const { pinia, router } = await setupApp("/orders/OTO20260101000001");
    const wrapper = mount(OrderDetailView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    await wrapper.find('[data-test="reject-button"]').trigger("click");
    await flushPromises();
    await wrapper.find('[data-test="reject-reason"] input').setValue("临时有事");
    await wrapper.find('[data-test="reject-confirm"]').trigger("click");
    await flushPromises();

    // 确实刷新过（首屏 1 次 + 冲突后刷新 1 次）
    expect(mockClient.getMasterOrder).toHaveBeenCalledTimes(2);

    // **弹窗关掉了**：留着只会让人再点一次、再撞一次注定失败的 404
    expect(rejectPopupOpen(wrapper)).toBe(false);

    // 页面顶部显示后端原话（**原样带上**）+ 刷新后的真实状态
    const text = wrapper.find('[data-test="action-error-text"]').text();
    expect(text).toContain("订单不存在");
    expect(text).toContain("已不适用");
    // **状态名跟页面上渲染的状态一致**：两边取**同一个来源**
    // （ORDER_STATUS_TEXT），别各写一个字面量——文案里硬编码成
    // 「已接单」的话，这条就会红（刷新后其实已经是「服务中」了）。
    const expectedStatusText = ORDER_STATUS_TEXT.IN_SERVICE;
    const statusText = wrapper.find('[data-test="order-status"]').text();
    expect(statusText).toContain(expectedStatusText);
    expect(text).toContain(expectedStatusText);
    // 用户有出路：返回列表
    expect(wrapper.find('[data-test="back-to-list"]').exists()).toBe(true);

    // 页面状态跟着刷新后的新状态走：PENDING_ACCEPT -> IN_SERVICE = 「完成服务」
    expect(wrapper.find('[data-test="finish-button"]').exists()).toBe(true);
    expect(wrapper.find('[data-test="start-button"]').exists()).toBe(false);
    expect(wrapper.find('[data-test="reject-button"]').exists()).toBe(false);

    // 再打开弹窗不会带着上一次的错误（openReject 会先清掉）。
    // 状态已经变成 ACCEPTED，页面上「拒单」按钮已经不在了（按钮跟着
    // 新状态走），所以这里直接调 openReject()——它才是「重新打开
    // 弹窗」的那一步。
    (wrapper.vm as unknown as { openReject: () => void }).openReject();
    await flushPromises();
    expect(rejectPopupOpen(wrapper)).toBe(true);
    expect(wrapper.find('[data-test="reject-server-error"]').exists()).toBe(false);
    expect(wrapper.find('[data-test="action-error"]').exists()).toBe(false);
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

  it("首屏加载失败点「重试」-> 请求在途时按钮 disabled（连点不会并发两次 GET）", async () => {
    // 连点两次「重试」会并发发两个 GET：后到的失败会把已经成功的加载盖掉
    // （页面显示出订单、却一个动作按钮都没有——状态被写成了不可信）。
    // 所以请求在途时按钮必须 disabled。
    let release: (value: unknown) => void = () => {};
    // 第一次（首屏）失败 -> 错误块出现；第二次（点「重试」）挂住不返回，
    // 好观察「在途」这个中间态。
    mockClient.getMasterOrder.mockRejectedValueOnce(
      new TypeError("Failed to fetch"),
    );
    mockClient.getMasterOrder.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          release = resolve;
        }),
    );
    mockClient.getMasterOrder.mockRejectedValue(new TypeError("Failed to fetch"));

    const { pinia, router } = await setupApp("/orders/OTO20260101000001");
    const wrapper = mount(OrderDetailView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    // 首屏失败 → 错误块里有「重试」
    expect(wrapper.find('[data-test="retry"]').exists()).toBe(true);

    await wrapper.find('[data-test="retry"]').trigger("click");
    await flushPromises();

    // 请求在途：按钮 disabled + loading
    const retry = wrapper.find('[data-test="retry"]');
    expect(retry.attributes("disabled")).toBeDefined();
    expect(retry.classes()).toContain("van-button--loading");

    // 放行收尾
    release(detail("ACCEPTED"));
    await flushPromises();
    expect(wrapper.find('[data-test="error-block"]').exists()).toBe(false);
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
  // UI-M2：刷新别把已有内容抽走 / 旧错误别挂着
  // ===================================================================

  it("动作成功后的刷新在途 -> 不用加载动画盖住页面（订单内容还在）", async () => {
    // 「刷新时别用加载动画盖住页面」：已经有订单内容时，刷新**不能**抽走内容。
    // 模板里是 v-if="loading && !order" —— 少了 && !order 的话，
    // 每次刷新都会闪一下加载动画、把订单内容藏起来。
    //
    // 第二次 getMasterOrder 挂住不返回，好观察「刷新在途」这个中间态。
    let release: (value: unknown) => void = () => {};
    mockClient.getMasterOrder
      .mockResolvedValueOnce(detail("PENDING_ACCEPT"))
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            release = resolve;
          }),
      );
    mockClient.acceptOrder.mockResolvedValue({
      order_no: "OTO20260101000001",
      status: "ACCEPTED",
    });

    const { pinia, router } = await setupApp("/orders/OTO20260101000001");
    const wrapper = mount(OrderDetailView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    await wrapper.find('[data-test="accept-button"]').trigger("click");
    await flushPromises();

    // 确实在刷新（初始 1 次 + 成功后刷新 1 次）
    expect(mockClient.getMasterOrder).toHaveBeenCalledTimes(2);

    // **刷新在途，但页面没有加载动画**：内容不抽走
    expect(wrapper.find('[data-test="loading"]').exists()).toBe(false);
    // 订单内容还在（没被加载动画盖住、也没白屏）
    expect(wrapper.find('[data-test="order-no"]').exists()).toBe(true);

    release(detail("ACCEPTED"));
    await flushPromises();
  });

  it("上一次动作失败留下的错误 -> 下一次动作成功后被清掉", async () => {
    // act() 开头的 actionError.value = ""：一次成功动作之后，
    // 页面顶部不该还挂着上一次的旧错误（用户会以为这次也失败了）。
    //
    // 用「开始服务」两次：第一次失败（409），第二次成功。
    // 为什么不是「接单失败 -> 接单成功」：按钮按订单状态给，
    // 待接单才给「接单」、已接单才给「开始服务」，同一个页面上
    // 这两个动作互斥（接单成功后这单就不再是「待接单」了）。
    mockClient.getMasterOrder.mockResolvedValue(detail("ACCEPTED"));
    mockClient.startService
      .mockRejectedValueOnce(
        new ApiError(409, "师傅当前不可接单：master_id=1", null),
      )
      .mockResolvedValueOnce({
        order_no: "OTO20260101000001",
        status: "IN_SERVICE",
        completed_at: null,
      });

    const { pinia, router } = await setupApp("/orders/OTO20260101000001");
    const wrapper = mount(OrderDetailView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    // 先制造一次失败：页面顶部挂上错误
    await wrapper.find('[data-test="start-button"]').trigger("click");
    await flushPromises();
    expect(wrapper.find('[data-test="action-error"]').exists()).toBe(true);
    expect(wrapper.find('[data-test="action-error-text"]').text()).toContain(
      "师傅当前不可接单",
    );

    // 再做一次动作，这次成功 -> 走刷新
    await wrapper.find('[data-test="start-button"]').trigger("click");
    await flushPromises();

    expect(mockClient.startService).toHaveBeenCalledTimes(2);
    // 成功之后确实刷新了详情
    expect(mockClient.getMasterOrder).toHaveBeenCalledTimes(2);
    // **上一次的旧错误被清掉**：页面顶部不再挂着它
    expect(wrapper.find('[data-test="action-error"]').exists()).toBe(false);
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
