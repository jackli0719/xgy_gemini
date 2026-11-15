/**
 * 时间格式化。
 *
 * 后端给的是 ISO 时间串（带时区）。这里只做展示用的格式化，
 * 不做时区换算——一律按浏览器本地时区显示，跟运营人员看到的时间一致。
 */

/** 把 ISO 时间串格式化成「YYYY-MM-DD HH:mm」。解析不了就原样返回。 */
export function formatDateTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const pad = (n: number): string => String(n).padStart(2, "0");
  return [
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`,
    `${pad(date.getHours())}:${pad(date.getMinutes())}`,
  ].join(" ");
}
