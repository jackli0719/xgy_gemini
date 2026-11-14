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

/** 成功状态码：下单是 201，其余业务动作是 200。 */
type SuccessStatus = 200 | 201;

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

/** 取某个 operation 成功响应的 JSON 类型。 */
export type ResponseOf<Op> = Op extends { responses: infer R }
  ? { [K in keyof R]: K extends SuccessStatus ? R[K] : never }[keyof R] extends {
      content: { "application/json": infer B };
    }
    ? B
    : never
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
type ListMyOrdersOp = operations["list_my_orders_api_v1_orders_get"];
type GetMyOrderOp = operations["get_my_order_api_v1_orders__order_no__get"];

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

    /**
     * 原始请求入口：给还没进 SDK 的新接口用。
     * 类型参数照抄生成的 operation 名字，别手写响应体形状。
     */
    request: send,
  };
}

/** SDK 实例类型（`createApiClient` 的返回值）。 */
export type ApiClient = ReturnType<typeof createApiClient>;
