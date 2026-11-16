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
