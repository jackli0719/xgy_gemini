/**
 * 前后端共用的时区契约。
 *
 * 数据来自 `packages/shared/timezone-contract.json`——**同一个文件**：
 * 后端 `apps/api/tests/test_timezone.py` 直接读那个 JSON，
 * 前端从这里读。两边对着同一张表断言，「前端显示的今天 == 后端 today()」
 * 才是有保证的，而不是靠两边各写各的注释。
 */
import raw from "../../timezone-contract.json";

export interface TimezoneContractCase {
  /** 时刻（UTC 的 ISO 串）。 */
  instant: string;
  /** 该时刻对应的业务日期（YYYY-MM-DD）。 */
  businessDate: string;
  /** 该时刻对应的业务时间（YYYY-MM-DD HH:mm）。 */
  businessDateTime: string;
  /** 这条用例在钉什么。 */
  why: string;
}

export const TIMEZONE_CONTRACT: {
  timeZone: string;
  note: string;
  cases: TimezoneContractCase[];
} = raw;
