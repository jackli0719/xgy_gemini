"""订单金额快照（纯逻辑）。

下单时把服务项的基准价快照成订单金额——金额的唯一来源。
服务端只接受从 service_item.base_price 取到的 Decimal，再经本模块校验与规范化；
前端传入的任何金额都不可信，本模块不提供「按前端金额下单」的入口。

职责边界：纯函数，不查库、不读配置、不写日志、不取时间戳。
"""
from __future__ import annotations

from decimal import Decimal

__all__ = ["PricingError", "snapshot_amount"]

# 金额统一量化到 2 位小数（分）
CENT = Decimal("0.01")

# 默认金额上限
DEFAULT_MAX_AMOUNT = Decimal("999999.99")


class PricingError(ValueError):
    """金额快照失败：类型、符号、区间或精度不合法。"""


def snapshot_amount(
    base_price: Decimal,
    *,
    max_amount: Decimal = DEFAULT_MAX_AMOUNT,
) -> Decimal:
    """把服务项基准价快照为订单金额。

    校验规则：
    - base_price 必须是 Decimal；int / float 一律拒绝。float 隐式转 Decimal
      会引入二进制精度误差，宁可让调用方显式构造 Decimal；
    - base_price 必须 >= 0；
    - base_price 必须 <= max_amount；
    - base_price 的十进制位数不超过 2 位。按十进制指数判断：
      Decimal('100.5') 的指数是 -1（合法），Decimal('100.123') 是 -3（拒绝）；
      尾随零也算位数——Decimal('100.500') 的指数是 -3，同样拒绝，
      要求调用方自己规范化，本函数不做四舍五入。

    返回量化到 2 位小数的 Decimal。
    """
    if not isinstance(base_price, Decimal):
        raise PricingError(
            "base_price 必须是 Decimal，收到 {}".format(type(base_price).__name__)
        )
    if base_price.is_nan() or base_price.is_infinite():
        raise PricingError("base_price 不能是 NaN 或 Infinity")
    if base_price < 0:
        raise PricingError("base_price 不能为负数：{}".format(base_price))
    if base_price > max_amount:
        raise PricingError(
            "base_price 超过上限 {}：{}".format(max_amount, base_price)
        )
    exponent = base_price.as_tuple().exponent
    if not isinstance(exponent, int) or exponent < -2:
        raise PricingError(
            "base_price 的小数位数不能超过 2 位：{}".format(base_price)
        )
    return base_price.quantize(CENT)
