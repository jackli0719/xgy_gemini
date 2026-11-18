/**
 * 错误文案翻译：网络错误 vs 业务错误。
 *
 * 与用户端（apps/h5-user/src/utils/error.ts）同一套口径，
 * 两边各留一份而不是抽到 shared：文案是产品的一部分，
 * 两端以后要改得不一样时不用再解开公共包。
 *
 * 这两类错误给用户的动作完全不同，不能用同一句话糊弄过去：
 *
 * - **网络错误**（断网 / 服务没起来 / 请求被中间层掐了）：
 *   用户能做的就是再试一次，所以统一提示「网络异常，请重试」，
 *   页面同时给出重试按钮；
 * - **业务错误**（时段被约满、订单状态已经变了……）：
 *   后端已经给了人话，原样显示即可——把后端的话改写一遍只会丢信息。
 *
 * 怎么认出网络错误：fetch 在网络层失败时抛的是 TypeError，
 * 但不同浏览器 / 运行时的文案不一样（浏览器 "Failed to fetch"，
 * Node "fetch failed"，Safari "Load failed"），所以按
 * 「TypeError + 已知文案」来认。别的 TypeError（比如代码写错）
 * 照常显示自己的 message——不能一律说成网络异常，那会把真 bug 藏起来。
 */
import { ApiError } from "@oto/shared/api";

/** 网络层失败的统一提示。 */
export const NETWORK_ERROR_MESSAGE = "网络异常，请重试";

/** fetch 网络失败时的已知文案（小写匹配）。 */
const NETWORK_ERROR_TEXTS = [
  "failed to fetch",
  "fetch failed",
  "load failed",
  "networkerror",
  "network request failed",
];

/** 这个错是不是网络层失败？ */
export function isNetworkError(err: unknown): boolean {
  if (!(err instanceof TypeError)) return false;
  const message = err.message.toLowerCase();
  return NETWORK_ERROR_TEXTS.some((text) => message.includes(text));
}

/**
 * 把一个异常翻译成给用户看的文案。
 *
 * @param err 捕获到的异常
 * @param fallback 既不是网络错也不是业务错时的兜底文案
 */
export function errorMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError) {
    // 业务错误：后端的 detail 就是人话，原样显示。
    return err.detail || fallback;
  }
  if (isNetworkError(err)) {
    return NETWORK_ERROR_MESSAGE;
  }
  if (err instanceof Error && err.message) {
    return err.message;
  }
  return fallback;
}
