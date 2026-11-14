"""订单金额快照规则的单测。"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.domain.pricing import PricingError, snapshot_amount


# ------------------------------------------------------------ 正常快照


@pytest.mark.parametrize(
    ("base_price", "expected"),
    [
        (Decimal("100.00"), Decimal("100.00")),
        (Decimal("0"), Decimal("0.00")),
        (Decimal("99.99"), Decimal("99.99")),
        (Decimal("100.5"), Decimal("100.50")),
        (Decimal("1"), Decimal("1.00")),
        (Decimal("999999.99"), Decimal("999999.99")),
    ],
)
def test_snapshot_amount_normal(base_price: Decimal, expected: Decimal) -> None:
    result = snapshot_amount(base_price)
    assert result == expected


@pytest.mark.parametrize(
    "base_price",
    [Decimal("0"), Decimal("100.00"), Decimal("99.99"), Decimal("100.5")],
)
def test_snapshot_amount_returns_two_decimal_decimal(base_price: Decimal) -> None:
    """返回值必须是 Decimal 且量化到 2 位小数，不能是 float。"""
    result = snapshot_amount(base_price)
    assert isinstance(result, Decimal)
    assert not isinstance(result, float)
    assert result.as_tuple().exponent == -2


# ------------------------------------------------------------ 拒绝非 Decimal


@pytest.mark.parametrize(
    "bad",
    [
        100,  # int
        100.0,  # float
        "100.00",  # str
        None,
        True,  # bool 是 int 的子类，同样不是 Decimal
    ],
)
def test_snapshot_amount_rejects_non_decimal(bad: object) -> None:
    """int / float 等一律拒绝，不做隐式转换。"""
    with pytest.raises(PricingError):
        snapshot_amount(bad)  # type: ignore[arg-type]


def test_snapshot_amount_rejects_float_even_if_integral() -> None:
    """float 100.0 与 int 100 数值相同，仍必须被拒绝。"""
    with pytest.raises(PricingError):
        snapshot_amount(100.0)  # type: ignore[arg-type]
    with pytest.raises(PricingError):
        snapshot_amount(100)  # type: ignore[arg-type]


# ------------------------------------------------------------ 拒绝非法取值


@pytest.mark.parametrize(
    "bad",
    [Decimal("-1"), Decimal("-0.01"), Decimal("-100.50")],
)
def test_snapshot_amount_rejects_negative(bad: Decimal) -> None:
    with pytest.raises(PricingError):
        snapshot_amount(bad)


def test_snapshot_amount_rejects_over_default_max() -> None:
    with pytest.raises(PricingError):
        snapshot_amount(Decimal("1000000.00"))


def test_snapshot_amount_rejects_over_custom_max() -> None:
    with pytest.raises(PricingError):
        snapshot_amount(Decimal("101"), max_amount=Decimal("100"))


def test_snapshot_amount_accepts_custom_max_boundary() -> None:
    assert snapshot_amount(Decimal("100"), max_amount=Decimal("100")) == Decimal(
        "100.00"
    )


def test_snapshot_amount_rejects_too_many_decimals() -> None:
    with pytest.raises(PricingError):
        snapshot_amount(Decimal("100.123"))


def test_snapshot_amount_rejects_trailing_zero_decimals() -> None:
    """Decimal('100.500') 的指数是 -3，属于 3 位小数，同样拒绝（不四舍五入）。"""
    with pytest.raises(PricingError):
        snapshot_amount(Decimal("100.500"))


@pytest.mark.parametrize(
    "bad",
    [Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")],
)
def test_snapshot_amount_rejects_nan_and_infinity(bad: Decimal) -> None:
    with pytest.raises(PricingError):
        snapshot_amount(bad)


# ------------------------------------------------------------ 异常结构


def test_pricing_error_is_value_error() -> None:
    assert issubclass(PricingError, ValueError)
    with pytest.raises(ValueError):
        snapshot_amount(Decimal("-1"))
