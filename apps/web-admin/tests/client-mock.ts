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
  /** PATCH /api/v1/provider/masters/{master_id} */
  updateProviderMaster: vi.fn(),
  /** POST /api/v1/orders/{order_id}/dispatch */
  dispatchOrder: vi.fn(),
  /** POST /api/v1/auth/login */
  login: vi.fn(),
  /** GET /api/v1/platform/providers */
  listPlatformProviders: vi.fn(),
  /** POST /api/v1/platform/providers */
  createProvider: vi.fn(),
  /** PATCH /api/v1/platform/providers/{provider_id} */
  updateProviderStatus: vi.fn(),
  /** POST /api/v1/platform/providers/{provider_id}/admin */
  createProviderAdmin: vi.fn(),
  /** GET /api/v1/platform/orders */
  listPlatformOrders: vi.fn(),
  /** GET /api/v1/platform/settlements */
  listPlatformSettlements: vi.fn(),
  /** POST /api/v1/settlements/{settlement_id}/confirm */
  confirmSettlement: vi.fn(),
  /** GET /api/v1/platform/categories */
  listPlatformCategories: vi.fn(),
  /** POST /api/v1/platform/categories */
  createPlatformCategory: vi.fn(),
  /** PATCH /api/v1/platform/categories/{category_id} */
  updatePlatformCategory: vi.fn(),
  /** POST /api/v1/platform/items */
  createPlatformItem: vi.fn(),
  /** PATCH /api/v1/platform/items/{item_id} */
  updatePlatformItem: vi.fn(),
  /** GET /api/v1/platform/masters（师傅入驻申请列表） */
  listPlatformOnboardingApplications: vi.fn(),
  /** POST /api/v1/platform/masters/{master_id}/review（入驻审核） */
  reviewMasterOnboarding: vi.fn(),
  /** GET /api/v1/masters/joinable-providers（可改判的服务商） */
  listJoinableProviders: vi.fn(),
};
