/**
 * 时间格式化（Web 后台）。
 *
 * 后端给的是 ISO 时间串（带时区，timestamptz 的绝对时刻）。
 * 这里按**业务时区**（默认 Asia/Shanghai）显示，跟后端的业务日期、
 * 跟用户看到的其他时间保持同一口径。
 *
 * 实现放在 `@oto/shared/timezone`：用 `Intl.DateTimeFormat` 显式指定
 * `timeZone`，**不跟着浏览器的本地时区走**——
 * 同一份数据在 UTC 的 CI 和国内运营的电脑上会显示成不同的时间。
 */
import { BUSINESS_TIME_ZONE, formatBusinessDateTime } from "@oto/shared/timezone";

export { BUSINESS_TIME_ZONE };

/** 把 ISO 时间串格式化成「YYYY-MM-DD HH:mm」。解析不了就原样返回。 */
export function formatDateTime(value: string): string {
  return formatBusinessDateTime(value);
}
