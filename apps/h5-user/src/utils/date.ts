/**
 * 日期工具（用户端）。
 *
 * 「今天」按**业务时区**算（默认 Asia/Shanghai），
 * 跟后端 `app/core/timezone.py` 的 `today()` 是同一个口径——
 * 两边差一天的话，用户在 H5 上看到的可选时段就跟后端对不上。
 *
 * 实现放在 `@oto/shared/timezone`：用 `Intl.DateTimeFormat` 显式指定
 * `timeZone`，**不依赖运行环境的本地时区**——
 * `new Date().getDate()` 在 UTC 的 CI 和国内用户的电脑上会给出不同的日期。
 */
import { BUSINESS_TIME_ZONE, formatBusinessDate } from "@oto/shared/timezone";

export { BUSINESS_TIME_ZONE };

/** 今天（业务时区）的 YYYY-MM-DD。 */
export function todayStr(now: Date = new Date()): string {
  return formatBusinessDate(now);
}

/**
 * 把 YYYY-MM-DD 往后挪若干天。
 *
 * 用 UTC 做加减：这个字符串只有日期没有时刻，
 * 走本地时区的话在 CI（UTC）和国内用户的电脑上会差一天。
 *
 * 格式不对就原样返回——调用方拿到的是一个能继续用的日期字符串，
 * 比抛异常好（页面上最多显示一个没变化的日期）。
 */
export function shiftDate(dateStr: string, days: number): string {
  const matched = /^(\d{4})-(\d{2})-(\d{2})$/.exec(dateStr);
  if (!matched) return dateStr;
  const [, year, month, day] = matched;
  const shifted = new Date(Date.UTC(Number(year), Number(month) - 1, Number(day)));
  shifted.setUTCDate(shifted.getUTCDate() + days);
  return shifted.toISOString().slice(0, 10);
}
