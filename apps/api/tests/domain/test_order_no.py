"""订单号生成规则的单测。"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.core.timezone import today
from app.domain.order_no import OrderNoError, generate_order_no

FIXED_NOW = datetime(2026, 11, 14, tzinfo=timezone.utc)


# ------------------------------------------------------------ 格式


def test_order_no_format() -> None:
    """OTO + 8 位日期 + 6 位数字，总长 17 位。"""
    number = generate_order_no(now=FIXED_NOW, rand=12345)
    assert len(number) == 17
    assert number.startswith("OTO")
    # 第 4~11 位：8 位日期数字
    assert len(number[3:11]) == 8
    assert number[3:11].isdigit()
    # 第 12~17 位：6 位随机数字
    assert len(number[11:17]) == 6
    assert number[11:17].isdigit()
    assert number[11:].isdigit()


def test_order_no_exact_value() -> None:
    """固定 now 与 rand 时输出完全确定。"""
    assert generate_order_no(now=FIXED_NOW, rand=12345) == "OTO20261114012345"


def test_order_no_rand_zero_is_zero_padded() -> None:
    number = generate_order_no(now=FIXED_NOW, rand=0)
    assert number == "OTO20261114000000"
    assert number.endswith("000000")


def test_order_no_rand_max() -> None:
    number = generate_order_no(now=FIXED_NOW, rand=999999)
    assert number == "OTO20261114999999"
    assert number.endswith("999999")


def test_order_no_date_part_follows_now() -> None:
    assert generate_order_no(now=datetime(2020, 1, 2, tzinfo=timezone.utc), rand=1) == (
        "OTO20200102000001"
    )


# ------------------------------------------------------------ 参数校验


@pytest.mark.parametrize("bad", [-1, 1000000, 1234567, 10**9])
def test_order_no_rejects_out_of_range_rand(bad: int) -> None:
    with pytest.raises(OrderNoError):
        generate_order_no(now=FIXED_NOW, rand=bad)


@pytest.mark.parametrize("bad", [1.5, "12345", None.__class__, True])
def test_order_no_rejects_non_integer_rand(bad: object) -> None:
    with pytest.raises(OrderNoError):
        generate_order_no(now=FIXED_NOW, rand=bad)  # type: ignore[arg-type]


def test_order_no_error_is_value_error() -> None:
    assert issubclass(OrderNoError, ValueError)
    with pytest.raises(ValueError):
        generate_order_no(now=FIXED_NOW, rand=-1)


# ------------------------------------------------------------ 默认时间


def test_order_no_defaults_to_business_today() -> None:
    """不传 now 时，日期部分等于**业务时区**的今天（app.core.timezone.today()）。

    不是 UTC 日期：UTC 23:30 时国内已经是次日，订单号上的日期要跟
    用户看到的那个白天一致。
    """
    number = generate_order_no()
    assert number[3:11] == today().strftime("%Y%m%d")


def test_order_no_at_2330_utc_uses_next_business_day() -> None:
    """now = UTC 23:30 时，日期部分是**次日**——不是 UTC 当天。

    UTC 2026-11-14 23:30 = 北京时间 2026-11-15 07:30，业务日期已经是 11-15。
    """
    number = generate_order_no(
        now=datetime(2026, 11, 14, 23, 30, tzinfo=timezone.utc), rand=1
    )
    assert number == "OTO20261115000001"


# ------------------------------------------------------------ 随机性


def test_order_no_distinct_for_distinct_rand() -> None:
    """给定不同的 rand，输出必然互不相同（确定性检查）。"""
    numbers = {generate_order_no(now=FIXED_NOW, rand=i) for i in range(1000)}
    assert len(numbers) == 1000


def test_order_no_random_source_is_not_degenerate() -> None:
    """随机源的抽样互异数要符合生日问题的期望值。

    6 位数字的取值空间是 10^6，抽样 n=10000 时，期望互异个数为
    M * (1 - (1 - 1/M)^n) ≈ 9500，因此互异数必然小于抽样数（存在生日碰撞）。
    这里断言互异数 >= 9000：既能抓出「随机源退化」这类真 bug
    （例如恒返回同一个值），又不会因正常的生日碰撞而误报。
    """
    numbers = [generate_order_no() for _ in range(10000)]
    assert len(numbers) == 10000
    assert len(set(numbers)) >= 9000
