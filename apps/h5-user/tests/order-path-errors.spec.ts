/**
 * UI-01：错误路径——不白屏。
 *
 * 这个文件**不 mock SDK**：真的走 client 里那层 fetch，用桩 fetch
 * 模拟 500 和网络中断。这样「后端 message 原样显示」和
 * 「网络错提示重试」是从 fetch 一直走到页面的完整路径，
 * 而不是「页面拿到一个假 Error 对象」。
 *
 * fetch 必须在模块被 import 之前换掉——client 在创建时就把
 * globalThis.fetch 抓在手里了，所以这里用 vi.hoisted。
 */
import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { fetchMock } = vi.hoisted(() => {
  const mock = vi.fn();
  // 必须在这里换：import 语句会被提升到所有顶层语句之前，
  // 页面模块 import 时就会创建 client、把当时的 globalThis.fetch 抓在手里。
  vi.stubGlobal("fetch", mock);
  return { fetchMock: mock };
});

import CatalogView from "@/views/CatalogView.vue";
import OrderNewView from "@/views/OrderNewView.vue";

import { setupApp } from "./helpers";

/** 造一个够 client 用的响应（client 只读 ok / status / text）。 */
function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    text: async () => JSON.stringify(body),
  } as unknown as Response;
}

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

describe("UI-01 错误路径（真实 SDK + 桩 fetch）", () => {
  beforeEach(() => {
    fetchMock.mockReset();
  });

  it("接口 500 时显示后端给的文案，不白屏", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(500, { detail: "服务暂时不可用，请稍后再试" }),
    );

    const { pinia, router } = await setupApp("/catalog");
    const wrapper = mount(CatalogView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    // 后端 message 原样显示
    expect(wrapper.find('[data-test="error"]').text()).toContain(
      "服务暂时不可用，请稍后再试",
    );
    // 不白屏：页面骨架还在，还能重试
    expect(wrapper.find(".page-title").exists()).toBe(true);
    expect(wrapper.find('[data-test="retry"]').exists()).toBe(true);
    expect(wrapper.find('[data-test="skeleton"]').exists()).toBe(false);
  });

  it("网络中断时提示「网络异常，请重试」", async () => {
    // 浏览器 fetch 断网时抛的就是 TypeError("Failed to fetch")
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));

    const { pinia, router } = await setupApp("/catalog");
    const wrapper = mount(CatalogView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    expect(wrapper.find('[data-test="error"]').text()).toContain("网络异常，请重试");
    expect(wrapper.find('[data-test="retry"]').exists()).toBe(true);
  });

  it("下单接口 500 时显示后端文案并留在下单页", async () => {
    fetchMock.mockImplementation(
      async (input: unknown, init?: { method?: string }) => {
        const url = String(input);
        const method = init?.method ?? "GET";
        if (method === "POST" && url.endsWith("/api/v1/orders")) {
          return jsonResponse(500, { detail: "时段已被约满" });
        }
        if (url.includes("/slots")) return jsonResponse(200, [SLOT]);
        if (url.includes("/items/")) return jsonResponse(200, ITEM);
        if (url.includes("/addresses")) return jsonResponse(200, [ADDRESS]);
        return jsonResponse(404, { detail: "未预期的请求：" + url });
      },
    );

    const { pinia, router } = await setupApp("/order/new?itemId=10&slotId=20");
    const wrapper = mount(OrderNewView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    await wrapper.find('[data-test="submit-order"]').trigger("click");
    await flushPromises();

    expect(wrapper.find('[data-test="error"]').text()).toContain("时段已被约满");
    // 下单失败要留在本页，不能跳走
    expect(router.currentRoute.value.path).toBe("/order/new");
  });
});
