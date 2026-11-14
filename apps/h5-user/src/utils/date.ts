/**
 * 日期工具。
 *
 * 「今天」按 **UTC** 算，跟后端保持一致（后端 app/services/user_queries.py
 * 的 today() 用的是 datetime.now(timezone.utc).date()）。
 *
 * 技术债：面向国内用户时应该按 Asia/Shanghai 算，
 * 后端和前端都要一起改，不能只改一边（不然会差一天）。
 */

/** 今天（UTC）的 YYYY-MM-DD。 */
export function todayStr(now: Date = new Date()): string {
  return now.toISOString().slice(0, 10);
}
