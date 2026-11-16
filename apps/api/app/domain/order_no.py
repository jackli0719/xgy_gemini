"""订单号生成（纯逻辑）。

格式：OTO + YYYYMMDD + 6 位数字，共 17 位。

职责边界：
- 不查库、不写日志；
- 唯一性由数据库 order.order_no 的 UNIQUE 约束兜底，本模块只保证格式正确、
  随机源不退化（能产出覆盖取值空间的有效随机数）；
- 不做重试——重试属于下单 service 层（T-07b-2b-2）的职责，本模块只产出候选值。

随机源用 secrets 而不是 random：random 是可预测的伪随机，
不适合用于订单号这类业务标识。

**订单号里的日期是业务日期**（默认 Asia/Shanghai，见 app.core.timezone）：
国内用户凌晨下单，订单号上的日期应该是国内的那个白天，
而不是 UTC 的昨天。
"""
from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - 只给类型检查用
    from zoneinfo import ZoneInfo

__all__ = ["OrderNoError", "generate_order_no"]

PREFIX = "OTO"
DATE_FORMAT = "%Y%m%d"
RANDOM_DIGITS = 6
RANDOM_BOUND = 10**RANDOM_DIGITS  # 6 位数字的取值空间 [0, 999999]


class OrderNoError(ValueError):
    """订单号生成的参数非法。"""


def generate_order_no(*, now: datetime | None = None, rand: int | None = None) -> str:
    """生成 17 位订单号候选值。

    - now：默认取**业务时区**的当前时间（app.core.timezone.now）；
      传入的时间会被换算到业务时区再取日期，naive datetime 按 UTC 解释
    - rand：0..999999 的整数，补零到 6 位；不传则用 secrets 生成
    """
    if rand is None:
        digits = secrets.randbelow(RANDOM_BOUND)
    else:
        if isinstance(rand, bool) or not isinstance(rand, int):
            raise OrderNoError(
                "rand 必须是整数，收到 {}".format(type(rand).__name__)
            )
        if rand < 0 or rand >= RANDOM_BOUND:
            raise OrderNoError(
                "rand 必须在 0..{} 之间，收到 {}".format(RANDOM_BOUND - 1, rand)
            )
        digits = rand

    moment = now if now is not None else _default_now()
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    # 日期部分取**业务日期**：同一个时刻，UTC 可能是昨天，
    # 国内已经是今天了。订单号上的日期要跟用户看到的一致。
    business_day = moment.astimezone(_local_tz()).strftime(DATE_FORMAT)
    return "{}{}{:0{}d}".format(
        PREFIX,
        business_day,
        digits,
        RANDOM_DIGITS,
    )


def _default_now() -> datetime:
    """默认的「现在」：业务时区（默认 Asia/Shanghai）。

    惰性导入 app.core.timezone：这个模块保持「导入时不读配置」的身份——
    只有真的要取默认时间时才需要配置。
    """
    from app.core.timezone import now as business_now

    return business_now()


def _local_tz() -> "ZoneInfo":
    """业务时区（惰性取，避免模块导入时就依赖配置）。"""
    from app.core.timezone import local_tz

    return local_tz()
