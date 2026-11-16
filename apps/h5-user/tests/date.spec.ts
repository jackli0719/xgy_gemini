/**
 * 日期工具的测试（用户端）。
 *
 * 核心是**前后端一致**：这里读的时区契约
 * （packages/shared/timezone-contract.json）与后端
 * apps/api/tests/test_timezone.py 读的是**同一份**，
 * 所以「前端显示的今天 == 后端 today()」不是靠约定，是靠两边对着同一张表断言。
 */
import { describe, expect, it } from "vitest";

import { BUSINESS_TIME_ZONE, TIMEZONE_CONTRACT } from "@oto/shared/timezone";

import { todayStr } from "@/utils/date";

describe("todayStr（业务时区）", () => {
  it("BUSINESS_TIME_ZONE 就是契约里的时区（不写第二份真相）", () => {
    expect(BUSINESS_TIME_ZONE).toBe(TIMEZONE_CONTRACT.timeZone);
  });

  it("逐条对上前后端共用的时区契约", () => {
    for (const item of TIMEZONE_CONTRACT.cases) {
      expect(todayStr(new Date(item.instant)), item.why).toBe(item.businessDate);
    }
  });

  it("UTC 23:30 下单 -> 业务日期是次日（+8 小时）", () => {
    // UTC 还是 11-14，国内已经是 11-15 早上 07:30
    expect(todayStr(new Date("2026-11-14T23:30:00Z"))).toBe("2026-11-15");
  });

  it("北京时间午夜整时，业务日期翻页", () => {
    expect(todayStr(new Date("2026-11-15T16:00:00Z"))).toBe("2026-11-16");
  });

  it("不跟着运行环境的本地时区走", () => {
    const original = process.env.TZ;
    try {
      for (const tz of ["UTC", "America/New_York", "Asia/Shanghai"]) {
        process.env.TZ = tz;
        expect(todayStr(new Date("2026-11-14T23:30:00Z")), tz).toBe("2026-11-15");
      }
    } finally {
      process.env.TZ = original;
    }
  });

  it("非法输入不炸", () => {
    expect(todayStr(new Date("not a date"))).toBe("");
  });
});
