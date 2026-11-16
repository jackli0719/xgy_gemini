/**
 * 师傅入驻申请页（/onboard）。
 *
 * 必测的四个点都在这里：
 *
 * 1. 没有申请 -> 显示表单（选服务商 + 填姓名 + 提交），
 *    提交时调 createOnboarding，参数是姓名与**想加入**的服务商；
 * 2. 已有待审核申请（PENDING）-> 显示「审核中」，**没有表单**；
 * 3. 已入职（ACTIVE）-> 自动跳订单页（不用再申请）；
 * 4. 提交返回 409（已有申请）-> 不报错，改成显示已有申请的状态。
 *
 * 另外钉住路由守卫：角色已是 MASTER 且状态是 ACTIVE 的师傅，
 * 进 /onboard 会直接被送到 /orders（不让重复申请）。
 */
import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import OnboardingView from "@/views/OnboardingView.vue";
import { ApiError } from "@oto/shared/api";

import { mockClient } from "./client-mock";
import { setupApp, waitForPath } from "./helpers";

vi.mock("@oto/shared/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@oto/shared/api")>();
  const { mockClient: client } = await import("./client-mock");
  return { ...actual, createApiClient: () => client };
});

/** 可申请的服务商。 */
const PROVIDERS = [
  { id: 1, name: "甲服务商" },
  { id: 2, name: "乙服务商" },
];

/** 一条入驻申请（字段与后端 OnboardingApplicationItem 对齐）。 */
function application(status: "PENDING" | "ACTIVE" | "DISABLED") {
  return {
    id: 5,
    real_name: "张师傅",
    phone: "13800000001",
    status,
    provider_id: 1,
    provider_name: "甲服务商",
    created_at: "2026-01-01T00:00:00Z",
  };
}

/** 后端「没有申请」用的是 404。 */
function notFound(): ApiError {
  return new ApiError(404, "师傅不存在", null);
}

describe("入驻申请页（师傅端）", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockClient.listJoinableProviders.mockResolvedValue({ items: PROVIDERS });
    mockClient.createOnboarding.mockResolvedValue(application("PENDING"));
    mockClient.getMyOnboarding.mockRejectedValue(notFound());
  });

  it("没有申请 -> 显示表单，选服务商 + 填姓名 + 提交 -> 参数正确", async () => {
    const { pinia, router } = await setupApp("/onboard");

    const wrapper = mount(OnboardingView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    // 表单在，服务商列表也拉了
    expect(wrapper.find('[data-test="apply-form"]').exists()).toBe(true);
    expect(wrapper.find('[data-test="provider-select"]').exists()).toBe(true);
    expect(mockClient.listJoinableProviders).toHaveBeenCalled();

    // 选第二家服务商（下拉的值由组件 emit 驱动）
    wrapper
      .findComponent({ name: "van-dropdown-item" })
      .vm.$emit("update:modelValue", 2);
    await wrapper.find('[data-test="name-field"] input').setValue("张师傅");
    await wrapper.find('[data-test="submit-onboarding"]').trigger("click");
    await flushPromises();

    expect(mockClient.createOnboarding).toHaveBeenCalledWith({
      real_name: "张师傅",
      target_provider_id: 2,
    });
  });

  it("已有待审核申请 -> 显示「审核中」，没有表单", async () => {
    mockClient.getMyOnboarding.mockResolvedValue(application("PENDING"));
    const { pinia, router } = await setupApp("/onboard");

    const wrapper = mount(OnboardingView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    expect(wrapper.find('[data-test="status-text"]').text()).toContain("审核中");
    expect(wrapper.find('[data-test="apply-form"]').exists()).toBe(false);
    // 已经有申请了，就不该再能提交
    expect(wrapper.find('[data-test="submit-onboarding"]').exists()).toBe(false);
  });

  it("已入职 -> 自动跳订单页", async () => {
    mockClient.getMyOnboarding.mockResolvedValue(application("ACTIVE"));
    const { pinia, router } = await setupApp("/onboard");

    mount(OnboardingView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    await waitForPath(router, "/orders");
  });

  it("提交返回 409（已有申请）-> 不报错，显示已有申请的状态", async () => {
    // 第一次问「有没有申请」是 404（还没有），提交之后就有了
    mockClient.getMyOnboarding
      .mockRejectedValueOnce(notFound())
      .mockResolvedValue(application("PENDING"));
    mockClient.createOnboarding.mockRejectedValue(
      new ApiError(409, "已有入驻申请", null),
    );
    const { pinia, router } = await setupApp("/onboard");

    const wrapper = mount(OnboardingView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    await wrapper.find('[data-test="name-field"] input').setValue("张师傅");
    await wrapper.find('[data-test="submit-onboarding"]').trigger("click");
    await flushPromises();

    // 409 不是错误：显示已有申请的状态，没有错误提示
    expect(wrapper.find('[data-test="error"]').exists()).toBe(false);
    expect(wrapper.find('[data-test="status-text"]').text()).toContain("审核中");
    expect(wrapper.find('[data-test="apply-form"]').exists()).toBe(false);
  });

  it("路由守卫：角色是 MASTER 且已入职 -> 进申请页会被送到订单页", async () => {
    mockClient.getMyOnboarding.mockResolvedValue(application("ACTIVE"));

    const { router } = await setupApp("/onboard", {
      user: { id: 7, name: "张师傅", role: "MASTER" },
    });

    await waitForPath(router, "/orders");
  });
});
