/**
 * 订单状态的中文文案。
 *
 * 状态取值来自后端的 12 态状态机（见 apps/api/app/models/enums.py），
 * 这里只做展示映射，不参与任何业务判断。
 */
import type { OrderStatus } from "@oto/shared/api";

export const ORDER_STATUS_TEXT: Record<OrderStatus, string> = {
  PENDING_PAY: "待支付",
  PENDING_DISPATCH: "待派单",
  PENDING_ACCEPT: "待接单",
  ACCEPTED: "已接单",
  IN_SERVICE: "服务中",
  PENDING_CONFIRM: "待确认",
  COMPLETED: "已完成",
  PENDING_SETTLE: "待结算",
  SETTLED: "已结算",
  CANCELLED: "已取消",
  REFUNDING: "退款中",
  REFUNDED: "已退款",
};
