/** 路由 query 取值的小工具。 */

/**
 * 取 query 里的第一个字符串值。
 *
 * vue-router 的 query 值类型是 `string | string[] | undefined`，
 * 这里统一成 `string | undefined`，页面里就不用到处判类型了。
 */
export function firstQuery(value: unknown): string | undefined {
  if (typeof value === "string") return value;
  if (Array.isArray(value) && typeof value[0] === "string") return value[0];
  return undefined;
}
