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
  /** GET /api/v1/catalog */
  listCategories: vi.fn(),
  /** GET /api/v1/catalog/{category_id}/items */
  listCategoryItems: vi.fn(),
  /** GET /api/v1/items/{item_id}/slots */
  listItemSlots: vi.fn(),
  /** POST /api/v1/orders */
  placeOrder: vi.fn(),
  /** GET /api/v1/orders */
  listMyOrders: vi.fn(),
  /** GET /api/v1/orders/{order_no} */
  getMyOrder: vi.fn(),
  /** POST /api/v1/orders/{order_no}/confirm */
  confirmService: vi.fn(),
};
