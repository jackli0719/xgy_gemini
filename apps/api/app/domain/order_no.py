"""订单号生成（纯逻辑）。

格式：OTO + YYYYMMDD + 6 位数字，共 17 位。

职责边界：
- 不查库、不读配置、不写日志；
- 唯一性由数据库 order.order_no 的 UNIQUE 约束兜底，本模块只保证格式正确、
  随机源不退化（能产出覆盖取值空间的有效随机数）；
- 不做重试——重试属于下单 service 层（T-07b-2b-2）的职责，本模块只产出候选值。

随机源用 secrets 而不是 random：random 是可预测的伪随机，
不适合用于订单号这类业务标识。
"""
from __future__ import annotations

import secrets
from datetime import datetime, timezone

__all__ = ["OrderNoError", "generate_order_no"]

PREFIX = "OTO"
DATE_FORMAT = "%Y%m%d"
RANDOM_DIGITS = 6
RANDOM_BOUND = 10**RANDOM_DIGITS  # 6 位数字的取值空间 [0, 999999]


class OrderNoError(ValueError):
    """订单号生成的参数非法。"""


def generate_order_no(*, now: datetime | None = None, rand: int | None = None) -> str:
    """生成 17 位订单号候选值。

    - now：默认取 datetime.now(timezone.utc)；naive datetime 按 UTC 解释
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

    moment = now if now is not None else datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return "{}{}{:0{}d}".format(
        PREFIX,
        moment.strftime(DATE_FORMAT),
        digits,
        RANDOM_DIGITS,
    )
