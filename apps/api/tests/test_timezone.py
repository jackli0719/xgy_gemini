"""时区口径的单测（不碰数据库）。

盯三件事：

1. **「今天」按业务时区算**：UTC 23:30（= 北京时间次日 07:30）时，
   业务日期必须是**次日**——这是本卡最核心的一条；
2. **前后端一致**：后端算出来的业务日期 / 业务时间，必须和
   ``packages/shared/timezone-contract.json`` 里的期望值一样；
   前端测试读同一份契约文件（见 apps/h5-user/tests/date.spec.ts
   与 apps/web-admin/tests/date.spec.ts），两边不可能各算各的。
3. **配置说了算**：时区名来自 ``settings.timezone``，写错直接拒绝启动。

契约文件在仓库根的 packages/shared/timezone-contract.json——
后端与前端读**同一份**，所以「前端日期显示与后端 today() 一致」
不是靠注释保证的，是靠两边都对着同一张表断言。
"""
from __future__ import annotations

import json
from datetime import date, datetime, time, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core import timezone as tz
from app.core.config import Settings, settings
from app.services import user_queries

# 仓库根：apps/api/tests/test_timezone.py -> 上溯 3 层
REPO_ROOT = Path(__file__).resolve().parents[3]
CONTRACT_PATH = REPO_ROOT / "packages" / "shared" / "timezone-contract.json"


def _contract() -> dict:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def _instant(value: str) -> datetime:
    """契约里的时刻都是 UTC 的 ISO 串（带 Z）。"""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# ------------------------------------------------------------ 配置


def test_default_timezone_is_asia_shanghai() -> None:
    """默认业务时区是 Asia/Shanghai（面向国内用户）。"""
    assert settings.timezone == "Asia/Shanghai"
    assert tz.local_tz().key == "Asia/Shanghai"


def test_contract_timezone_matches_settings() -> None:
    """契约文件里的时区名必须跟配置一致——不然两边算的根本不是同一个时区。"""
    assert _contract()["timeZone"] == settings.timezone


def test_invalid_timezone_is_rejected_at_startup() -> None:
    """时区名写错直接拒绝启动，不等到运行时才报 zoneinfo 的 KeyError。"""
    with pytest.raises(ValidationError):
        Settings(
            database_url="postgresql+asyncpg://u:p@localhost:5432/db",
            jwt_secret="x" * 40,
            timezone="Asia/ShangHai",
        )


# ------------------------------------------------------------ 「今天」


def test_today_is_next_day_at_2330_utc(monkeypatch) -> None:
    """UTC 23:30 下单 -> 业务日期是**次日**（+8 小时）。

    这是本卡的核心用例：UTC 日期还是 11-14，但国内已经是 11-15 早上，
    「今天」必须是 11-15——查当天时段、订单号日期都靠它。
    """
    fixed = datetime(2026, 11, 14, 23, 30, tzinfo=timezone.utc)
    monkeypatch.setattr(tz, "now", lambda: fixed)

    assert tz.today() == date(2026, 11, 15)
    # 用户侧 service 的 today() 也必须是同一个口径
    assert user_queries.today() == date(2026, 11, 15)


def test_today_is_same_day_before_1600_utc(monkeypatch) -> None:
    """UTC 15:59（= 北京时间 23:59）时，业务日期还是当天。"""
    fixed = datetime(2026, 11, 15, 15, 59, tzinfo=timezone.utc)
    monkeypatch.setattr(tz, "now", lambda: fixed)

    assert tz.today() == date(2026, 11, 15)


def test_today_never_uses_utc_date(monkeypatch) -> None:
    """today() 不能等于 UTC 日期——那正是本卡要修的 bug。

    做法：造一个「UTC 与业务日期不同」的时刻，断言两者不等，
    且 today() 取的是业务日期这一侧。
    """
    fixed = datetime(2026, 11, 14, 23, 30, tzinfo=timezone.utc)
    monkeypatch.setattr(tz, "now", lambda: fixed)

    assert fixed.date() == date(2026, 11, 14)  # UTC 日期
    assert tz.today() == date(2026, 11, 15)  # 业务日期


# ------------------------------------------------------------ 业务日期换算


def test_business_date_matches_contract() -> None:
    """业务日期的换算逐条对上契约文件。"""
    for case in _contract()["cases"]:
        moment = _instant(case["instant"])
        assert tz.business_date(moment).isoformat() == case["businessDate"], case


def test_business_date_of_naive_datetime_treats_it_as_utc() -> None:
    """naive 时间按 UTC 解释（库里出来的是带时区的值，别把裸时间戳当成别的时区）。"""
    naive = datetime(2026, 11, 14, 23, 30)
    assert tz.business_date(naive) == date(2026, 11, 15)


def test_business_datetime_is_in_business_timezone() -> None:
    """业务日期 + 墙钟时间 -> 业务时区的时间点（+08:00）。"""
    moment = tz.business_datetime(date(2026, 11, 15), time(9, 0))

    assert moment.utcoffset().total_seconds() == 8 * 3600
    assert moment.isoformat() == "2026-11-15T09:00:00+08:00"
    # 同一个时刻的 UTC 表示
    assert moment.astimezone(timezone.utc).isoformat() == "2026-11-15T01:00:00+00:00"


def test_now_utc_is_utc() -> None:
    """存库时间戳走 UTC（绝对时刻）。"""
    assert tz.now_utc().tzinfo is timezone.utc
    assert tz.now().utcoffset().total_seconds() == 8 * 3600


def test_as_utc_normalizes_both_forms() -> None:
    """带时区的转成 UTC；naive 的按 UTC 解释。"""
    assert tz.as_utc(datetime(2026, 1, 1, 8, 0)).isoformat() == "2026-01-01T08:00:00+00:00"
    assert (
        tz.as_utc(datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)).isoformat()
        == "2026-01-01T08:00:00+00:00"
    )
