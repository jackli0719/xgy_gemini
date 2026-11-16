"""时区口径：全仓库的「现在」「今天」都从这里取。

**两套时间，各有各的用途，不要混**：

1. **业务时区**（``settings.timezone``，默认 Asia/Shanghai）：
   面向人的口径——「今天」是哪天、下单时段是不是还在将来、
   超时自动确认的 N 小时从哪一刻起算、T+1 结算的「满一天」满的是哪个白天。
2. **UTC**：存库时间戳（timestamptz）。库里存的是**绝对时刻**，
   显示与业务日期判断都在读出来之后做。

**DB 里存 timestamptz 不动**：本模块不碰存储，只负责在「取业务日期」
的那一处把绝对时刻换算成业务时区（``business_date`` / ``business_datetime``）。

**为什么不能拿 ``datetime.now(timezone.utc).date()`` 当「今天」**：
那是**绝对时刻**再取 UTC 日期。国内用户凌晨下单时，UTC 日期还停在昨天，
于是「今天」比用户以为的早一天——查当天时段会差一天、下单的订单号日期
也会错一天。所以业务日期一律走 ``today()``（业务时区）。

**为什么不用裸 ``datetime.now(timezone.utc)``**：它和「业务时区的现在」
长得一样，但含义完全不同（绝对时刻 vs 业务墙钟）。全仓库统一从这里取，
读代码的人就不用再猜某个 ``now`` 到底是哪一种。
"""
from __future__ import annotations

from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from app.core.config import settings

__all__ = [
    "as_utc",
    "business_date",
    "business_datetime",
    "local_tz",
    "now",
    "now_utc",
    "today",
]


def local_tz() -> ZoneInfo:
    """业务时区（默认 Asia/Shanghai）。

    每次调用都重新解析：配置可以在运行期改（测试里会 monkeypatch），
    缓存下来的 ZoneInfo 就成了旧值。
    """
    return ZoneInfo(settings.timezone)


def now() -> datetime:
    """业务时区的「现在」（带时区）。

    要的是**墙钟时间**（几点几分、今天几号）就用它；
    要的是**绝对时刻**（存库、算间隔）就用 ``now_utc()``。
    """
    return datetime.now(local_tz())


def now_utc() -> datetime:
    """UTC 的「现在」（带时区）——存库时间戳用。

    库里是 timestamptz：写进去的是绝对时刻，跟时区无关。
    """
    return datetime.now(timezone.utc)


def today() -> date:
    """业务时区的「今天」。

    先换算再取日期（而不是直接 ``now().date()``）：``now()`` 给的是
    业务时区的时间，换算这一步是幂等的，但这样写「今天就是业务日期」
    这件事就不依赖于 ``now()`` 到底带的是哪个时区。
    """
    return business_date(now())


def business_date(value: datetime) -> date:
    """把一个时间戳换算成**业务日期**。

    这是「只在取业务日期处转换」的那一处：库里存的是绝对时刻，
    要说「这单是哪天的」，先换到业务时区再取日期。

    naive 时间按 UTC 解释（库里出来的是带时区的值；真拿到 naive 的，
    当成 UTC 至少不会凭空差出几个小时）。
    """
    return as_utc(value).astimezone(local_tz()).date()


def business_datetime(day: date, clock: time) -> datetime:
    """把「业务日期 + 墙钟时间」组装成一个带业务时区的时间点。

    用它把时段（``schedule_slot.date`` + ``start_time``）这类
    **墙钟**数据变成可比较的时间点——时段说的是「北京时间的几点」，
    不是「UTC 的几点」。
    """
    return datetime.combine(day, clock, tzinfo=local_tz())


def as_utc(value: datetime) -> datetime:
    """把时间戳统一成 UTC（naive 按 UTC 解释）。"""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
