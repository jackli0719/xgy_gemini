import { vi } from "vitest";

/**
 * 被测页面用到的 SDK 方法桩。
 *
 * 单独放一个文件，是为了让 vi.mock 的工厂（会被提升到文件顶部）
 * 能通过动态 import 拿到同一个实例 —— 页面和测试断言的是同一批 vi.fn()。
 *
 * 方法名和 @oto/shared 的 client 一一对应（不另造一套 API）。
 */
export const mockClient = {
  /** GET /api/v1/provider/orders */
  listProviderOrders: vi.fn(),
  /** GET /api/v1/provider/masters */
  listProviderMasters: vi.fn(),
  /** POST /api/v1/orders/{order_id}/dispatch */
  dispatchOrder: vi.fn(),
  /** POST /api/v1/auth/login */
  login: vi.fn(),
};
