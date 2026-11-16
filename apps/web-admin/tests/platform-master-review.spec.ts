/**
 * 必测（平台侧师傅入驻审核页，FE-06b）：
 *
 * 1. **列表渲染 + 操作按钮显示**：mock 返回 2 条待审核申请，
 *    表格出 2 行，每行有「通过 / 驳回」两个按钮；
 * 2. **通过**：调 `reviewMasterOnboarding`，参数含 `decision: "APPROVE"`；
 *    改判服务商时额外带 `target_provider_id`；
 * 3. **驳回**：弹窗填理由 -> 参数含 `decision: "REJECT"` + `reason`；
 * 4. **非 PLATFORM_ADMIN 进不来**：路由守卫不放行 + 菜单不显示入口。
 *
 * 另外钉两条边界：
 *
 * - **前端不带 operator / 身份字段**：操作人身份由后端按 token 决定，
 *   请求参数里只有师傅 id 与审核结论（卡片约束）；
 * - **请求体里没有 provider_id**：归属由平台确认，不是客户端自报的东西
 *   （全仓 openapi 契约测试也禁止该字段名），改判走 target_provider_id。
 */
import { flushPromises, mount } from "@vue/test-utils";
import { ElPagination, ElSelect } from "element-plus";
import { beforeEach, describe, expect, it, vi } from "vitest";

import App from "@/App.vue";
import PlatformMasterReviewView from "@/views/PlatformMasterReviewView.vue";
import type { CurrentUser } from "@/stores/session";

import { mockClient } from "./client-mock";
import { setupApp, waitForPath } from "./helpers";

vi.mock("@oto/shared/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@oto/shared/api")>();
  const { mockClient: client } = await import("./client-mock");
  return { ...actual, createApiClient: () => client };
});

/** 两条待审核的入驻申请。 */
const APPLICATIONS = {
  items: [
    {
      id: 901,
      real_name: "张师傅",
      phone: "13900000001",
      status: "PENDING",
      provider_id: 301,
      provider_name: "甲服务商",
      created_at: "2026-11-14T23:30:00Z",
    },
    {
      id: 902,
      real_name: "李师傅",
      phone: "13900000002",
      status: "PENDING",
      provider_id: 302,
      provider_name: "乙服务商",
      created_at: "2026-11-15T02:00:00Z",
    },
  ],
  total: 2,
  page: 1,
  limit: 20,
};

/** 可以改判过去的服务商（营业中的那些）。 */
const PROVIDERS = {
  items: [
    { id: 301, name: "甲服务商" },
    { id: 302, name: "乙服务商" },
    { id: 303, name: "丙服务商" },
  ],
};

const PLATFORM_ADMIN: CurrentUser = {
  id: 1,
  nickname: "平台管理员",
  phone: "13700000001",
  role: "PLATFORM_ADMIN",
  provider_id: null,
};

const PLATFORM_OPS: CurrentUser = {
  id: 2,
  nickname: "平台运营",
  phone: "13700000002",
  role: "PLATFORM_OPS",
  provider_id: null,
};

async function mountReviewPage() {
  const { pinia, router } = await setupApp("/platform/masters/review", {
    currentUser: PLATFORM_ADMIN,
  });
  const wrapper = mount(PlatformMasterReviewView, {
    global: { plugins: [pinia] },
  });
  await flushPromises();
  return { wrapper, router };
}

describe("平台侧师傅入驻审核页", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    mockClient.listPlatformOnboardingApplications.mockResolvedValue(APPLICATIONS);
    mockClient.listJoinableProviders.mockResolvedValue(PROVIDERS);
    mockClient.reviewMasterOnboarding.mockResolvedValue({
      id: 901,
      real_name: "张师傅",
      status: "ACTIVE",
      provider_id: 301,
      provider_name: "甲服务商",
      created_at: "2026-11-14T23:30:00Z",
    });
  });

  it("列表渲染 2 行 + 每行有通过 / 驳回按钮", async () => {
    const { wrapper } = await mountReviewPage();

    // 只看待审核的申请（后端默认一页 20 条，超出的翻页看）
    expect(mockClient.listPlatformOnboardingApplications).toHaveBeenCalledWith({
      status: "PENDING",
      page: 1,
      limit: 20,
    });

    const rows = wrapper.findAll(".el-table__body-wrapper tbody tr");
    expect(rows).toHaveLength(2);
    expect(wrapper.text()).toContain("张师傅");
    expect(wrapper.text()).toContain("甲服务商");
    expect(wrapper.text()).toContain("李师傅");
    expect(wrapper.text()).toContain("乙服务商");

    const approves = wrapper.findAll('[data-test="approve-btn"]');
    const rejects = wrapper.findAll('[data-test="reject-btn"]');
    expect(approves).toHaveLength(2);
    expect(rejects).toHaveLength(2);
  });

  it("翻页：调列表接口带新的 page（待审核超过一页时后面的申请也审得到）", async () => {
    const { wrapper } = await mountReviewPage();

    const pager = wrapper.findComponent(ElPagination);
    pager.vm.$emit("current-change", 2);
    await flushPromises();

    expect(mockClient.listPlatformOnboardingApplications).toHaveBeenLastCalledWith({
      status: "PENDING",
      page: 2,
      limit: 20,
    });
  });

  it("通过：调 review 参数含 decision=APPROVE（不改判就不带 target_provider_id）", async () => {
    const { wrapper } = await mountReviewPage();

    await wrapper.findAll('[data-test="approve-btn"]')[0].trigger("click");
    await flushPromises();
    expect(wrapper.find('[data-test="approve-dialog"]').exists()).toBe(true);

    await wrapper.find('[data-test="submit-approve-btn"]').trigger("click");
    await flushPromises();

    expect(mockClient.reviewMasterOnboarding).toHaveBeenCalledTimes(1);
    expect(mockClient.reviewMasterOnboarding).toHaveBeenCalledWith(
      { master_id: 901 },
      { decision: "APPROVE" },
    );
    // 审完刷新列表：这一行不该还留在表格里
    expect(mockClient.listPlatformOnboardingApplications).toHaveBeenCalledTimes(2);
  });

  it("通过时改判服务商：参数带 target_provider_id", async () => {
    const { wrapper } = await mountReviewPage();

    await wrapper.findAll('[data-test="approve-btn"]')[1].trigger("click");
    await flushPromises();

    // 下拉选另一家服务商
    wrapper.findComponent(ElSelect).vm.$emit("update:modelValue", 303);
    await flushPromises();

    await wrapper.find('[data-test="submit-approve-btn"]').trigger("click");
    await flushPromises();

    expect(mockClient.reviewMasterOnboarding).toHaveBeenCalledWith(
      { master_id: 902 },
      { decision: "APPROVE", target_provider_id: 303 },
    );
  });

  it("通过时把下拉清空 = 沿用申请（不传 target_provider_id）", async () => {
    const { wrapper } = await mountReviewPage();

    await wrapper.findAll('[data-test="approve-btn"]')[0].trigger("click");
    await flushPromises();

    // 选完又清空：el-select 清空时回填的可能是 undefined / 空串，
    // 只有「是数字」才算真的改判了
    const select = wrapper.findComponent(ElSelect);
    select.vm.$emit("update:modelValue", 303);
    await flushPromises();
    select.vm.$emit("update:modelValue", undefined);
    await flushPromises();

    await wrapper.find('[data-test="submit-approve-btn"]').trigger("click");
    await flushPromises();

    expect(mockClient.reviewMasterOnboarding).toHaveBeenCalledWith(
      { master_id: 901 },
      { decision: "APPROVE" },
    );
    // 关键：不能只是「值是 undefined」，而是**根本没有这个字段**
    // （undefined 会被 JSON.stringify 丢掉，空串会被后端校验成 422）
    const body = mockClient.reviewMasterOnboarding.mock.calls[0][1];
    expect("target_provider_id" in body).toBe(false);
  });

  it("通过时把下拉清成空串 = 沿用申请（不传 target_provider_id）", async () => {
    const { wrapper } = await mountReviewPage();

    await wrapper.findAll('[data-test="approve-btn"]')[0].trigger("click");
    await flushPromises();

    const select = wrapper.findComponent(ElSelect);
    select.vm.$emit("update:modelValue", "");
    await flushPromises();

    await wrapper.find('[data-test="submit-approve-btn"]').trigger("click");
    await flushPromises();

    const body = mockClient.reviewMasterOnboarding.mock.calls[0][1];
    expect("target_provider_id" in body).toBe(false);
  });

  it("申请里的服务商已被冻结：必须改判才能通过（不给后端一个必然 404 的请求）", async () => {
    // 可加入列表里没有 301（申请的是甲服务商）——它被冻结了
    mockClient.listJoinableProviders.mockResolvedValue({
      items: [{ id: 303, name: "丙服务商" }],
    });
    const { wrapper } = await mountReviewPage();

    await wrapper.findAll('[data-test="approve-btn"]')[0].trigger("click");
    await flushPromises();
    expect(wrapper.find('[data-test="reassign-hint"]').exists()).toBe(true);

    // 不改判就提交：拦下来，不调接口
    await wrapper.find('[data-test="submit-approve-btn"]').trigger("click");
    await flushPromises();
    expect(mockClient.reviewMasterOnboarding).not.toHaveBeenCalled();

    // 改判到营业中的那家 -> 带上 target_provider_id
    wrapper.findComponent(ElSelect).vm.$emit("update:modelValue", 303);
    await flushPromises();
    await wrapper.find('[data-test="submit-approve-btn"]').trigger("click");
    await flushPromises();

    expect(mockClient.reviewMasterOnboarding).toHaveBeenCalledWith(
      { master_id: 901 },
      { decision: "APPROVE", target_provider_id: 303 },
    );
  });

  it("服务商列表拉不到：不做「必须改判」的前置判断，但要提示（交给后端判）", async () => {
    mockClient.listJoinableProviders.mockRejectedValue(new Error("network down"));
    const { wrapper } = await mountReviewPage();

    // 列表拉失败要说出来：不然空下拉看着像「没有别的服务商」
    expect(wrapper.find('[data-test="providers-error"]').exists()).toBe(true);

    await wrapper.findAll('[data-test="approve-btn"]')[0].trigger("click");
    await flushPromises();
    expect(wrapper.find('[data-test="reassign-hint"]').exists()).toBe(false);
    expect(wrapper.find('[data-test="providers-error-hint"]').exists()).toBe(true);

    await wrapper.find('[data-test="submit-approve-btn"]').trigger("click");
    await flushPromises();
    expect(mockClient.reviewMasterOnboarding).toHaveBeenCalledTimes(1);
  });

  it("打开通过弹窗时重新拉一次可改判服务商（列表可能已经过期）", async () => {
    const { wrapper } = await mountReviewPage();
    expect(mockClient.listJoinableProviders).toHaveBeenCalledTimes(1);

    await wrapper.findAll('[data-test="approve-btn"]')[0].trigger("click");
    await flushPromises();

    expect(mockClient.listJoinableProviders).toHaveBeenCalledTimes(2);
  });

  it("一家营业中的服务商都没有：说清楚「无法通过，可驳回」", async () => {
    mockClient.listJoinableProviders.mockResolvedValue({ items: [] });
    const { wrapper } = await mountReviewPage();

    await wrapper.findAll('[data-test="approve-btn"]')[0].trigger("click");
    await flushPromises();

    expect(wrapper.find('[data-test="no-provider-hint"]').exists()).toBe(true);
    // 占位文案不能说「沿用申请的服务商」——那正是被禁止的选项
    const select = wrapper.findComponent(ElSelect);
    expect(select.props("placeholder")).not.toBe("沿用申请的服务商");
  });

  it("必须改判时：占位文案提示必选", async () => {
    mockClient.listJoinableProviders.mockResolvedValue({
      items: [{ id: 303, name: "丙服务商" }],
    });
    const { wrapper } = await mountReviewPage();

    await wrapper.findAll('[data-test="approve-btn"]')[0].trigger("click");
    await flushPromises();

    expect(wrapper.findComponent(ElSelect).props("placeholder")).toBe(
      "请选择改判到哪一家（必选）",
    );
  });

  it("驳回：弹窗填理由 -> 参数含 decision=REJECT + reason", async () => {
    const { wrapper } = await mountReviewPage();

    await wrapper.findAll('[data-test="reject-btn"]')[0].trigger("click");
    await flushPromises();
    expect(wrapper.find('[data-test="reject-dialog"]').exists()).toBe(true);

    await wrapper.find('[data-test="reject-reason-field"] textarea').setValue("资质不齐");
    await flushPromises();

    await wrapper.find('[data-test="submit-reject-btn"]').trigger("click");
    await flushPromises();

    expect(mockClient.reviewMasterOnboarding).toHaveBeenCalledTimes(1);
    expect(mockClient.reviewMasterOnboarding).toHaveBeenCalledWith(
      { master_id: 901 },
      { decision: "REJECT", reason: "资质不齐" },
    );
  });

  it("驳回不填理由：不调接口", async () => {
    const { wrapper } = await mountReviewPage();

    await wrapper.findAll('[data-test="reject-btn"]')[0].trigger("click");
    await flushPromises();

    await wrapper.find('[data-test="submit-reject-btn"]').trigger("click");
    await flushPromises();

    expect(mockClient.reviewMasterOnboarding).not.toHaveBeenCalled();
  });

  it("请求里没有身份字段与 provider_id", async () => {
    const { wrapper } = await mountReviewPage();

    await wrapper.findAll('[data-test="approve-btn"]')[0].trigger("click");
    await flushPromises();
    await wrapper.find('[data-test="submit-approve-btn"]').trigger("click");
    await flushPromises();

    const [params, body] = mockClient.reviewMasterOnboarding.mock.calls[0];
    expect(params).not.toHaveProperty("operator");
    expect(params).not.toHaveProperty("operator_id");
    expect(params).not.toHaveProperty("provider_id");
    expect(body).not.toHaveProperty("operator");
    expect(body).not.toHaveProperty("provider_id");
  });

  it("角色不是平台管理员：路由守卫不放行这页", async () => {
    const { router } = await setupApp("/platform/masters/review", {
      currentUser: PLATFORM_OPS,
    });

    // 被弹回首页（首页按角色落到订单总览）
    await waitForPath(router, "/platform/orders");
  });

  it("菜单入口只有平台管理员看得到", async () => {
    const admin = await setupApp("/platform/orders", {
      currentUser: PLATFORM_ADMIN,
    });
    const adminWrapper = mount(App, {
      global: { plugins: [admin.pinia, admin.router] },
    });
    await flushPromises();
    expect(
      adminWrapper.find('[data-test="platform-master-review-link"]').exists(),
    ).toBe(true);

    localStorage.clear();
    const ops = await setupApp("/platform/orders", { currentUser: PLATFORM_OPS });
    const opsWrapper = mount(App, {
      global: { plugins: [ops.pinia, ops.router] },
    });
    await flushPromises();
    expect(
      opsWrapper.find('[data-test="platform-master-review-link"]').exists(),
    ).toBe(false);
  });
});
