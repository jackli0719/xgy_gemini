/**
 * 基于生成类型的 fetch 封装（**手写**，不是自动生成的）。
 *
 * 类型全部来自 ./schema（由 openapi-typescript 从 apps/api/openapi.json 生成），
 * 这个文件只做三件事：拼 URL、带 token、把非 2xx 翻译成 ApiError。
 *
 * 约定：
 *
 * - **baseUrl 默认空字符串**：走相对路径，由调用方决定是同源代理还是跨域直连。
 * - **token 由 getToken() 提供**：可以是同步或异步函数；返回 null / undefined
 *   表示不带 Authorization 头。后端所有业务接口都要 Bearer token。
 * - **非 2xx 一律抛 ApiError**：文案取后端返回的 `detail`。
 *   后端的业务异常响应体统一是 `{"detail": "..."}`
 *   （见 apps/api/app/api/v1/errors.py），422 的字段校验错误是
 *   `{"detail": [{loc, msg, type}, ...]}`。
 * - **金额等字段一律是 string**：后端金额是 Decimal，OpenAPI 里映射成 string，
 *   前端要自己转数字，不要直接当 number 用。
 */
import type { components, operations } from "./schema";

export type Schemas = components["schemas"];

/** 订单状态（后端状态机的 12 态）。 */
export type OrderStatus = Schemas["OrderStatus"];
/** 支付状态。 */
export type PayStatus = Schemas["PayStatus"];
/** 结算单状态。 */
export type SettlementStatus = Schemas["SettlementStatus"];

/** 成功状态码：下单是 201，其余业务动作是 200，删除是 204（无响应体）。 */
type SuccessStatus = 200 | 201 | 204;

/** 取某个 operation 的路径参数。 */
export type PathParamsOf<Op> = Op extends { parameters: { path: infer P } } ? P : Record<string, never>;

/** 取某个 operation 的查询参数（没有查询参数的接口是 never）。 */
export type QueryParamsOf<Op> = Op extends { parameters: { query?: infer Q } }
  ? NonNullable<Q>
  : Record<string, never>;

/** 取某个 operation 的请求体（没有请求体时是 never）。 */
export type RequestBodyOf<Op> = Op extends {
  requestBody: { content: { "application/json": infer B } };
}
  ? B
  : never;

/**
 * 取某个响应里的 JSON 响应体类型。
 *
 * 没有响应体（204 之类）时是 void——不是 unknown：
 * unknown 会让「这个接口到底返回什么」变成一问三不知，调用方只能瞎转。
 */
type JsonBodyOf<S> = S extends { content: { "application/json": infer B } }
  ? B
  : void;

/** 取某个 operation 成功响应的 JSON 类型。 */
export type ResponseOf<Op> = Op extends { responses: infer R }
  ? JsonBodyOf<{ [K in keyof R]: K extends SuccessStatus ? R[K] : never }[keyof R]>
  : never;

export class ApiError extends Error {
  /** HTTP 状态码。 */
  readonly status: number;
  /** 后端给的文案（业务异常就是那句话，422 是字段错误列表的 JSON 文本）。 */
  readonly detail: string;
  /** 原始响应体（已解析成对象；不是 JSON 时是原文）。 */
  readonly body: unknown;

  constructor(status: number, detail: string, body: unknown) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    this.body = body;
  }
}

export interface ApiClientOptions {
  /** 接口根路径，默认空字符串（相对路径）。 */
  baseUrl?: string;
  /** 取 Bearer token 的方式，返回 null / undefined 表示不带鉴权头。 */
  getToken?: () => string | null | undefined | Promise<string | null | undefined>;
  /** 自定义 fetch（测试或 SSR 环境用）。 */
  fetch?: typeof globalThis.fetch;
  /** 额外的固定请求头。 */
  headers?: Record<string, string>;
}

type PlaceOrderOp = operations["create_order_api_v1_orders_post"];
type StartServiceOp = operations["start_order_service_api_v1_orders__order_no__start_post"];
type FinishServiceOp = operations["finish_order_service_api_v1_orders__order_no__finish_post"];
type ConfirmServiceOp = operations["confirm_order_service_api_v1_orders__order_no__confirm_post"];
type AcceptOrderOp = operations["accept_order_api_v1_orders__order_no__accept_post"];
type RejectOrderOp = operations["reject_order_api_v1_orders__order_no__reject_post"];
type DispatchOrderOp = operations["dispatch_order_api_v1_orders__order_id__dispatch_post"];
type ConfirmSettlementOp = operations["confirm_settlement_api_v1_settlements__settlement_id__confirm_post"];
type MockPayNotifyOp = operations["mock_pay_notify_api_v1_pay_mock_notify_post"];
type ListCategoriesOp = operations["list_categories_api_v1_catalog_get"];
type ListCategoryItemsOp = operations["list_category_items_api_v1_catalog__category_id__items_get"];
type ListItemSlotsOp = operations["list_item_slots_api_v1_items__item_id__slots_get"];
type GetItemOp = operations["get_item_api_v1_items__item_id__get"];
type ListMyOrdersOp = operations["list_my_orders_api_v1_orders_get"];
type GetMyOrderOp = operations["get_my_order_api_v1_orders__order_no__get"];
type ListAddressesOp = operations["list_addresses_api_v1_addresses_get"];
type CreateAddressOp = operations["create_address_api_v1_addresses_post"];
type UpdateAddressOp = operations["update_address_api_v1_addresses__address_id__put"];
type DeleteAddressOp = operations["delete_address_api_v1_addresses__address_id__delete"];
type LoginOp = operations["login_api_v1_auth_login_post"];
type ListProviderOrdersOp = operations["list_provider_orders_api_v1_provider_orders_get"];
type ListProviderMastersOp = operations["list_provider_masters_api_v1_provider_masters_get"];
type UpdateProviderMasterOp = operations["update_provider_master_api_v1_provider_masters__master_id__patch"];
type ListMasterOrdersOp = operations["list_master_orders_api_v1_master_orders_get"];
type GetMasterOrderOp = operations["get_master_order_api_v1_master_orders__order_no__get"];
type GetMasterProfileOp = operations["get_master_profile_api_v1_master_profile_get"];
type ListPlatformProvidersOp = operations["list_platform_providers_api_v1_platform_providers_get"];
type CreatePlatformProviderOp = operations["create_platform_provider_api_v1_platform_providers_post"];
type UpdatePlatformProviderStatusOp = operations["update_platform_provider_status_api_v1_platform_providers__provider_id__patch"];
type CreatePlatformProviderAdminOp = operations["create_platform_provider_admin_api_v1_platform_providers__provider_id__admin_post"];
type ListPlatformOrdersOp = operations["list_platform_orders_api_v1_platform_orders_get"];
type ListPlatformCategoriesOp = operations["list_platform_categories_api_v1_platform_categories_get"];
type CreatePlatformCategoryOp = operations["create_platform_category_api_v1_platform_categories_post"];
type UpdatePlatformCategoryOp = operations["update_platform_category_api_v1_platform_categories__category_id__patch"];
type CreatePlatformItemOp = operations["create_platform_item_api_v1_platform_items_post"];
type UpdatePlatformItemOp = operations["update_platform_item_api_v1_platform_items__item_id__patch"];


/** 从错误响应体里挑出文案。 */
function detailOf(body: unknown): string | undefined {
  if (typeof body === "string" && body) return body;
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (detail !== undefined && detail !== null) return JSON.stringify(detail);
  }
  return undefined;
}

/** 拼查询串：undefined 的参数不拼（等于不传这个参数）。 */
function buildUrl(
  baseUrl: string,
  path: string,
  query?: Record<string, string | number | undefined>,
): string {
  if (!query) return `${baseUrl}${path}`;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined) continue;
    params.set(key, String(value));
  }
  const search = params.toString();
  if (!search) return `${baseUrl}${path}`;
  return `${baseUrl}${path}${path.includes("?") ? "&" : "?"}${search}`;
}

export function createApiClient(options: ApiClientOptions = {}) {
  const baseUrl = options.baseUrl ?? "";
  const doFetch = options.fetch ?? globalThis.fetch;

  async function send<Op>(
    method: string,
    path: string,
    init: {
      body?: RequestBodyOf<Op>;
      query?: Record<string, string | number | undefined>;
    } = {},
  ): Promise<ResponseOf<Op>> {
    const headers: Record<string, string> = { ...options.headers };
    const token = await options.getToken?.();
    if (token) headers["Authorization"] = `Bearer ${token}`;

    let payload: string | undefined;
    if (init.body !== undefined) {
      headers["Content-Type"] = "application/json";
      payload = JSON.stringify(init.body);
    }

    const response = await doFetch(`${buildUrl(baseUrl, path, init.query)}`, {
      method,
      headers,
      body: payload,
    });

    const text = await response.text();
    let body: unknown = null;
    if (text) {
      try {
        body = JSON.parse(text);
      } catch {
        body = text;
      }
    }

    if (!response.ok) {
      throw new ApiError(
        response.status,
        detailOf(body) ?? `请求失败：HTTP ${response.status}`,
        body,
      );
    }
    return body as ResponseOf<Op>;
  }

  return {
    /** 下单。请求体只有 item_id / slot_id / address_id，金额由服务端算。 */
    placeOrder(body: RequestBodyOf<PlaceOrderOp>): Promise<ResponseOf<PlaceOrderOp>> {
      return send<PlaceOrderOp>("POST", "/api/v1/orders", { body });
    },

    /** 师傅开工。 */
    startService(params: PathParamsOf<StartServiceOp>): Promise<ResponseOf<StartServiceOp>> {
      return send<StartServiceOp>(
        "POST",
        `/api/v1/orders/${encodeURIComponent(params.order_no)}/start`,
      );
    },

    /** 师傅完工。 */
    finishService(params: PathParamsOf<FinishServiceOp>): Promise<ResponseOf<FinishServiceOp>> {
      return send<FinishServiceOp>(
        "POST",
        `/api/v1/orders/${encodeURIComponent(params.order_no)}/finish`,
      );
    },

    /** 客户确认完成。 */
    confirmService(params: PathParamsOf<ConfirmServiceOp>): Promise<ResponseOf<ConfirmServiceOp>> {
      return send<ConfirmServiceOp>(
        "POST",
        `/api/v1/orders/${encodeURIComponent(params.order_no)}/confirm`,
      );
    },

    /** 师傅接单。 */
    acceptOrder(params: PathParamsOf<AcceptOrderOp>): Promise<ResponseOf<AcceptOrderOp>> {
      return send<AcceptOrderOp>(
        "POST",
        `/api/v1/orders/${encodeURIComponent(params.order_no)}/accept`,
      );
    },

    /** 师傅拒单（要带原因）。 */
    rejectOrder(
      params: PathParamsOf<RejectOrderOp>,
      body: RequestBodyOf<RejectOrderOp>,
    ): Promise<ResponseOf<RejectOrderOp>> {
      return send<RejectOrderOp>(
        "POST",
        `/api/v1/orders/${encodeURIComponent(params.order_no)}/reject`,
        { body },
      );
    },

    /** 派单（平台侧把订单派给某个师傅）。 */
    dispatchOrder(
      params: PathParamsOf<DispatchOrderOp>,
      body: RequestBodyOf<DispatchOrderOp>,
    ): Promise<ResponseOf<DispatchOrderOp>> {
      return send<DispatchOrderOp>(
        "POST",
        `/api/v1/orders/${encodeURIComponent(String(params.order_id))}/dispatch`,
        { body },
      );
    },

    /** 财务确认结算单。 */
    confirmSettlement(
      params: PathParamsOf<ConfirmSettlementOp>,
    ): Promise<ResponseOf<ConfirmSettlementOp>> {
      return send<ConfirmSettlementOp>(
        "POST",
        `/api/v1/settlements/${encodeURIComponent(String(params.settlement_id))}/confirm`,
      );
    },

    /** mock 支付回调（只在 dev 环境开放）。 */
    mockPayNotify(
      body: RequestBodyOf<MockPayNotifyOp>,
    ): Promise<ResponseOf<MockPayNotifyOp>> {
      return send<MockPayNotifyOp>("POST", "/api/v1/pay/mock-notify", { body });
    },

    // -----------------------------------------------------------------
    // 只读查询
    // -----------------------------------------------------------------

    /** 品类树（一级品类 + 递归子品类）。 */
    listCategories(): Promise<ResponseOf<ListCategoriesOp>> {
      return send<ListCategoriesOp>("GET", "/api/v1/catalog");
    },

    /** 某品类下的服务项（只含直接归属该品类的）。 */
    listCategoryItems(
      params: PathParamsOf<ListCategoryItemsOp>,
    ): Promise<ResponseOf<ListCategoryItemsOp>> {
      return send<ListCategoryItemsOp>(
        "GET",
        `/api/v1/catalog/${encodeURIComponent(String(params.category_id))}/items`,
      );
    },

    /** 某服务项某天的可预约时段（只返回 available > 0 的）。 */
    listItemSlots(params: {
      item_id: number;
      /** YYYY-MM-DD */
      date: string;
    }): Promise<ResponseOf<ListItemSlotsOp>> {
      return send<ListItemSlotsOp>(
        "GET",
        `/api/v1/items/${encodeURIComponent(String(params.item_id))}/slots`,
        { query: { date: params.date } },
      );
    },

    /** 我的订单列表（后端 limit 上限 100，超过按 100 算）。 */
    listMyOrders(
      params: QueryParamsOf<ListMyOrdersOp> = {},
    ): Promise<ResponseOf<ListMyOrdersOp>> {
      return send<ListMyOrdersOp>("GET", "/api/v1/orders", {
        query: { limit: params.limit, offset: params.offset },
      });
    },

    /** 订单详情（只能看自己的，别人的返回 404）。 */
    getMyOrder(params: PathParamsOf<GetMyOrderOp>): Promise<ResponseOf<GetMyOrderOp>> {
      return send<GetMyOrderOp>(
        "GET",
        `/api/v1/orders/${encodeURIComponent(params.order_no)}`,
      );
    },

    /** 单个服务项（名称 / 基准价 / 时长）。 */
    getItem(params: PathParamsOf<GetItemOp>): Promise<ResponseOf<GetItemOp>> {
      return send<GetItemOp>(
        "GET",
        `/api/v1/items/${encodeURIComponent(String(params.item_id))}`,
      );
    },

    // -----------------------------------------------------------------
    // 服务商侧
    //
    // 这两个接口**不传 provider_id**：服务端按 token 里的归属过滤，
    // 客户端自报归属等于让它自己挑租户（R1）。
    // -----------------------------------------------------------------

    /**
     * 本商订单列表（默认待派单）。
     *
     * `status` 省略时后端按 PENDING_DISPATCH 处理。
     */
    listProviderOrders(
      params: QueryParamsOf<ListProviderOrdersOp> = {},
    ): Promise<ResponseOf<ListProviderOrdersOp>> {
      return send<ListProviderOrdersOp>("GET", "/api/v1/provider/orders", {
        query: { status: params.status, limit: params.limit, offset: params.offset },
      });
    },

    /** 本商师傅列表（id / 姓名 / 手机号 / 评分 / 状态）。 */
    listProviderMasters(): Promise<ResponseOf<ListProviderMastersOp>> {
      return send<ListProviderMastersOp>("GET", "/api/v1/provider/masters");
    },

    /**
     * 改本商师傅的状态（启用 / 休假 / 停用）。
     *
     * **不传 provider_id**：能改哪个师傅由服务端按 token 里的归属决定，
     * 改别家的师傅会得到 404。
     */
    updateProviderMaster(
      params: PathParamsOf<UpdateProviderMasterOp>,
      body: RequestBodyOf<UpdateProviderMasterOp>,
    ): Promise<ResponseOf<UpdateProviderMasterOp>> {
      return send<UpdateProviderMasterOp>(
        "PATCH",
        `/api/v1/provider/masters/${encodeURIComponent(String(params.master_id))}`,
        { body },
      );
    },

    // -----------------------------------------------------------------
    // 师傅端
    //
    // 这几个接口**不传 master_id**：师傅身份由服务端按 token 里的 user_id
    // 查 master 表得到，客户端自报身份等于自己挑单（R1）。
    // -----------------------------------------------------------------

    /**
     * 我的订单列表（只返回派给我的单）。
     *
     * `status` 只接受师傅端的三种：PENDING_ACCEPT / ACCEPTED / IN_SERVICE。
     */
    listMasterOrders(
      params: QueryParamsOf<ListMasterOrdersOp> = {},
    ): Promise<ResponseOf<ListMasterOrdersOp>> {
      return send<ListMasterOrdersOp>("GET", "/api/v1/master/orders", {
        query: { status: params.status, limit: params.limit, offset: params.offset },
      });
    },

    /** 订单详情（只查得到派给我的单，别人的是 404）。 */
    getMasterOrder(params: PathParamsOf<GetMasterOrderOp>): Promise<ResponseOf<GetMasterOrderOp>> {
      return send<GetMasterOrderOp>(
        "GET",
        `/api/v1/master/orders/${encodeURIComponent(params.order_no)}`,
      );
    },

    /** 我的资料（姓名 / 评分 / 状态 / 所属服务商）。 */
    getMasterProfile(): Promise<ResponseOf<GetMasterProfileOp>> {
      return send<GetMasterProfileOp>("GET", "/api/v1/master/profile");
    },

    // -----------------------------------------------------------------
    // 平台侧：服务商管理
    //
    // 这几个接口只有 PLATFORM_ADMIN 能调（服务端按 token 里的角色判）。
    // 「管哪一个服务商」是路径参数（provider_id），**身份不传**——
    // 客户端自报身份等于自己挑身份（R1）。
    // -----------------------------------------------------------------

    /**
     * 服务商列表（平台侧，全部服务商）。
     *
     * `status` 省略表示不按状态过滤。
     */
    listPlatformProviders(
      params: QueryParamsOf<ListPlatformProvidersOp> = {},
    ): Promise<ResponseOf<ListPlatformProvidersOp>> {
      return send<ListPlatformProvidersOp>("GET", "/api/v1/platform/providers", {
        query: {
          status: params.status ?? undefined,
          page: params.page,
          limit: params.limit,
        },
      });
    },

    /**
     * 新建服务商（初始状态「待审核」，状态不由请求体决定）。
     */
    createProvider(
      body: RequestBodyOf<CreatePlatformProviderOp>,
    ): Promise<ResponseOf<CreatePlatformProviderOp>> {
      return send<CreatePlatformProviderOp>("POST", "/api/v1/platform/providers", { body });
    },

    /**
     * 改服务商状态（审核通过 / 冻结 / 解冻）。
     *
     * 当前状态不允许这次流转时服务端返回 409。
     */
    updateProviderStatus(
      params: PathParamsOf<UpdatePlatformProviderStatusOp>,
      body: RequestBodyOf<UpdatePlatformProviderStatusOp>,
    ): Promise<ResponseOf<UpdatePlatformProviderStatusOp>> {
      return send<UpdatePlatformProviderStatusOp>(
        "PATCH",
        `/api/v1/platform/providers/${encodeURIComponent(String(params.provider_id))}`,
        { body },
      );
    },

    /**
     * 给某个服务商建管理员账号（入参只有手机号）。
     *
     * 手机号已被占用时服务端返回 409。
     */
    createProviderAdmin(
      params: PathParamsOf<CreatePlatformProviderAdminOp>,
      body: RequestBodyOf<CreatePlatformProviderAdminOp>,
    ): Promise<ResponseOf<CreatePlatformProviderAdminOp>> {
      return send<CreatePlatformProviderAdminOp>(
        "POST",
        `/api/v1/platform/providers/${encodeURIComponent(String(params.provider_id))}/admin`,
        { body },
      );
    },

    // -----------------------------------------------------------------
    // 平台侧：订单总览 + 目录管理
    //
    // 这几个接口 PLATFORM_ADMIN / PLATFORM_OPS 都能调（服务端按 token 里的
    // 角色判）。订单总览是**全量**（不按用户过滤），这是平台侧的特权，
    // 来自角色而不是来自请求参数——所以这里也没有 user_id。
    // -----------------------------------------------------------------

    /**
     * 平台订单总览（全量，可按状态 / 服务商筛选）。
     *
     * `status` / `provider_id` 省略表示不按它筛选。
     */
    listPlatformOrders(
      params: QueryParamsOf<ListPlatformOrdersOp> = {},
    ): Promise<ResponseOf<ListPlatformOrdersOp>> {
      return send<ListPlatformOrdersOp>("GET", "/api/v1/platform/orders", {
        query: {
          status: params.status ?? undefined,
          provider_id: params.provider_id ?? undefined,
          page: params.page,
          limit: params.limit,
        },
      });
    },

    /** 品类树（含子品类与各品类下的服务项，含已停用的）。 */
    listPlatformCategories(): Promise<ResponseOf<ListPlatformCategoriesOp>> {
      return send<ListPlatformCategoriesOp>("GET", "/api/v1/platform/categories");
    },

    /** 新建品类（初始状态「启用」，状态不由请求体决定）。 */
    createPlatformCategory(
      body: RequestBodyOf<CreatePlatformCategoryOp>,
    ): Promise<ResponseOf<CreatePlatformCategoryOp>> {
      return send<CreatePlatformCategoryOp>("POST", "/api/v1/platform/categories", {
        body,
      });
    },

    /**
     * 改品类（名称 / 排序 / 状态）。
     *
     * `expected_status` 是乐观锁：带上「我以为的旧状态」，
     * 服务端发现实际状态已经变了就返回 409。
     */
    updatePlatformCategory(
      params: PathParamsOf<UpdatePlatformCategoryOp>,
      body: RequestBodyOf<UpdatePlatformCategoryOp>,
    ): Promise<ResponseOf<UpdatePlatformCategoryOp>> {
      return send<UpdatePlatformCategoryOp>(
        "PATCH",
        `/api/v1/platform/categories/${encodeURIComponent(String(params.category_id))}`,
        { body },
      );
    },

    /** 新建服务项（入参含品类 id、名称、基准价、时长）。 */
    createPlatformItem(
      body: RequestBodyOf<CreatePlatformItemOp>,
    ): Promise<ResponseOf<CreatePlatformItemOp>> {
      return send<CreatePlatformItemOp>("POST", "/api/v1/platform/items", { body });
    },

    /**
     * 改服务项（名称 / 基准价 / 时长 / 状态）。
     *
     * 改价会写审计日志（服务端的事，前端不用管）。
     */
    updatePlatformItem(
      params: PathParamsOf<UpdatePlatformItemOp>,
      body: RequestBodyOf<UpdatePlatformItemOp>,
    ): Promise<ResponseOf<UpdatePlatformItemOp>> {
      return send<UpdatePlatformItemOp>(
        "PATCH",
        `/api/v1/platform/items/${encodeURIComponent(String(params.item_id))}`,
        { body },
      );
    },

    // -----------------------------------------------------------------
    // 收货地址
    //
    // 地址归属由服务端按 token 决定：这里不传 user_id，
    // 也拿不到别人的地址（改 / 删别人的地址会得到 404）。
    // -----------------------------------------------------------------

    /** 我的地址列表。 */
    listAddresses(): Promise<ResponseOf<ListAddressesOp>> {
      return send<ListAddressesOp>("GET", "/api/v1/addresses");
    },

    /** 新建地址。 */
    createAddress(
      body: RequestBodyOf<CreateAddressOp>,
    ): Promise<ResponseOf<CreateAddressOp>> {
      return send<CreateAddressOp>("POST", "/api/v1/addresses", { body });
    },

    /** 修改地址（整体替换四个字段）。 */
    updateAddress(
      params: PathParamsOf<UpdateAddressOp>,
      body: RequestBodyOf<UpdateAddressOp>,
    ): Promise<ResponseOf<UpdateAddressOp>> {
      return send<UpdateAddressOp>(
        "PUT",
        `/api/v1/addresses/${encodeURIComponent(String(params.address_id))}`,
        { body },
      );
    },

    /** 删除地址（204，没有响应体）。 */
    deleteAddress(params: PathParamsOf<DeleteAddressOp>): Promise<void> {
      return send<DeleteAddressOp>(
        "DELETE",
        `/api/v1/addresses/${encodeURIComponent(String(params.address_id))}`,
      );
    },

    // -----------------------------------------------------------------
    // 登录
    // -----------------------------------------------------------------

    /**
     * 手机号 + 验证码登录。
     *
     * 整个 H5 里**只有这一个接口不需要 token**（它本身就是拿 token 的入口）。
     */
    login(body: RequestBodyOf<LoginOp>): Promise<ResponseOf<LoginOp>> {
      return send<LoginOp>("POST", "/api/v1/auth/login", { body });
    },

    /**
     * 原始请求入口：给还没进 SDK 的新接口用。
     * 类型参数照抄生成的 operation 名字，别手写响应体形状。
     */
    request: send,
  };
}

/** SDK 实例类型（`createApiClient` 的返回值）。 */
export type ApiClient = ReturnType<typeof createApiClient>;
