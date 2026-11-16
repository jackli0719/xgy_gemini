/**
 * 时间格式化的测试（Web 后台）。
 *
 * 核心是**前后端一致**：这里读的时区契约
 * （packages/shared/timezone-contract.json）与后端
 * apps/api/tests/test_timezone.py 读的是**同一份**，
 * 所以「运营看到的确认时间 == 后端算的业务时间」有同一张表兜着。
 */
import { describe, expect, it } from "vitest";

import { TIMEZONE_CONTRACT } from "@oto/shared/timezone";

import { formatDateTime } from "@/utils/date";

describe("formatDateTime（业务时区）", () => {
  it("逐条对上前后端共用的时区契约", () => {
    for (const item of TIMEZONE_CONTRACT.cases) {
      expect(formatDateTime(item.instant), item.why).toBe(item.businessDateTime);
    }
  });

  it("UTC 23:30 的时刻显示成北京时间的次日 07:30", () => {
    expect(formatDateTime("2026-11-14T23:30:00Z")).toBe("2026-11-15 07:30");
  });

  it("北京时间午夜整显示成 00:00（不是 24:00）", () => {
    expect(formatDateTime("2026-11-15T16:00:00Z")).toBe("2026-11-16 00:00");
  });

  it("不跟着运行环境的本地时区走", () => {
    const original = process.env.TZ;
    try {
      for (const tz of ["UTC", "America/New_York", "Asia/Shanghai"]) {
        process.env.TZ = tz;
        expect(formatDateTime("2026-11-14T23:30:00Z"), tz).toBe(
          "2026-11-15 07:30",
        );
      }
    } finally {
      process.env.TZ = original;
    }
  });

  it("解析不了就原样返回", () => {
    expect(formatDateTime("not a date")).toBe("not a date");
  });
});
