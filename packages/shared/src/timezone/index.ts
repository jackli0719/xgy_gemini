/**
 * 时区：全仓库的「业务日期」口径。
 *
 * 后端的业务时区是 `settings.timezone`（默认 Asia/Shanghai，见
 * `apps/api/app/core/timezone.py`）。前端必须跟它一致——两边算出来的
 * 「今天」差一天的话，用户看到的可选时段、订单时间就会跟后端对不上。
 *
 * **一律用 Intl.DateTimeFormat 显式指定 timeZone**，不要用
 * `date.getDate()` / `date.toLocaleDateString()`：
 * - `getDate()` 取的是**运行环境本地时区**的日期，同一份数据在
 *   UTC 的 CI 和国内用户的电脑上会显示成不同的日期；
 * - `toLocaleDateString()` 不带 timeZone 时同样跟着运行环境走。
 *
 * 显式指定之后，格式与时区都由代码说了算，不受运行环境影响。
 */
export const BUSINESS_TIME_ZONE = "Asia/Shanghai";

export { TIMEZONE_CONTRACT } from "./contract";
export type { TimezoneContractCase } from "./contract";

/**
 * 业务时区的格式化器。
 *
 * `hourCycle: "h23"` 而不是 `hour12: false`：后者在部分引擎里会按
 * locale 默认给出 h24（午夜显示成 24:00），h23 明确是 00-23。
 */
const businessFormatter = new Intl.DateTimeFormat("zh-CN", {
  timeZone: BUSINESS_TIME_ZONE,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});

/**
 * 取一次格式化后的各个字段。
 *
 * 用 formatToParts 而不是直接拼格式化后的字符串：不同 locale 的
 * 分隔符不一样（zh-CN 是 "2026/11/16 08:30"），拼字符串就得去猜分隔符，
 * 换个浏览器或 locale 就散架。
 */
function partsOf(value: Date | string): Map<string, string> | null {
  const date = typeof value === "string" ? new Date(value) : value;
  if (Number.isNaN(date.getTime())) return null;
  const parts = new Map<string, string>();
  for (const part of businessFormatter.formatToParts(date)) {
    parts.set(part.type, part.value);
  }
  return parts;
}

/** 业务时区的日期，格式 YYYY-MM-DD。解析不了就原样返回。 */
export function formatBusinessDate(value: Date | string): string {
  const parts = partsOf(value);
  if (!parts) return typeof value === "string" ? value : "";
  return `${parts.get("year")}-${parts.get("month")}-${parts.get("day")}`;
}

/** 业务时区的日期时间，格式 YYYY-MM-DD HH:mm。解析不了就原样返回。 */
export function formatBusinessDateTime(value: Date | string): string {
  const parts = partsOf(value);
  if (!parts) return typeof value === "string" ? value : "";
  return `${parts.get("year")}-${parts.get("month")}-${parts.get("day")} ${parts.get(
    "hour",
  )}:${parts.get("minute")}`;
}
