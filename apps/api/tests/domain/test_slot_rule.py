"""预约时段库存扣减规则的单测。"""
from __future__ import annotations

import inspect

import pytest

from app.domain.slot_rule import (
    SlotError,
    SlotInvalidError,
    SlotNotReservableError,
    assert_reservable,
    available,
    can_reserve,
)


# ----------------------------------------------------------------- available


@pytest.mark.parametrize(
    ("capacity", "used", "expected"),
    [
        (5, 0, 5),
        (5, 3, 2),
        (5, 4, 1),
        (5, 5, 0),  # 已满
        (5, 6, 0),  # 异常数据：used > capacity，返回 0 而不是负数
        (0, 0, 0),
        (0, 1, 0),
        (1, 0, 1),
    ],
)
def test_available(capacity: int, used: int, expected: int) -> None:
    result = available(capacity, used)
    assert result == expected
    assert result >= 0


def test_available_never_returns_negative() -> None:
    assert available(3, 10) == 0
    assert available(0, 5) == 0


# --------------------------------------------------------------- can_reserve


@pytest.mark.parametrize(
    ("capacity", "used", "count", "expected"),
    [
        (1, 0, 1, True),  # 刚好够
        (5, 4, 1, True),  # used = capacity - 1
        (5, 5, 1, False),  # 已满
        (5, 5, 0, False),  # count > 0 不满足
        (5, 5, -1, False),
        (5, 3, 2, True),
        (5, 3, 3, False),  # 恰好超出
        (5, -1, 1, False),  # 异常数据：used < 0
        (5, 6, 1, False),  # 异常数据：used > capacity
        (0, 0, 1, False),  # capacity <= 0
        (0, 1, 1, False),
    ],
)
def test_can_reserve(
    capacity: int, used: int, count: int, expected: bool
) -> None:
    assert can_reserve(capacity, used, count) is expected


def test_can_reserve_default_count_is_one() -> None:
    """count 的默认值必须是 1。"""
    default = inspect.signature(can_reserve).parameters["count"].default
    assert default == 1
    assert can_reserve(1, 0) is True
    assert can_reserve(1, 1) is False


def test_can_reserve_never_allows_anomalous_data() -> None:
    """异常数据必须判 False，不得静默放行。"""
    assert can_reserve(5, 6, 1) is False
    assert can_reserve(5, -1, 1) is False
    assert can_reserve(0, 0, 1) is False
    assert can_reserve(5, 0, 0) is False
    assert can_reserve(5, 0, -1) is False


# --------------------------------------------------------- assert_reservable


def test_assert_reservable_accepts_legal_case() -> None:
    assert assert_reservable(5, 3, 2) is None
    assert assert_reservable(5, 4, 1) is None
    assert assert_reservable(1, 0, 1) is None
    assert assert_reservable(5, 0) is None  # 默认 count = 1


@pytest.mark.parametrize(
    ("capacity", "used", "count"),
    [
        (5, 3, 3),  # used + count > capacity
        (1, 1, 1),
        (5, 0, 6),
    ],
)
def test_assert_reservable_raises_not_reservable(
    capacity: int, used: int, count: int
) -> None:
    """数据合法但库存不足 → SlotNotReservableError，消息含三个数值。"""
    with pytest.raises(SlotNotReservableError) as excinfo:
        assert_reservable(capacity, used, count)
    message = str(excinfo.value)
    assert str(capacity) in message
    assert str(used) in message
    assert str(count) in message


@pytest.mark.parametrize(
    ("capacity", "used", "count"),
    [
        (5, 0, 0),  # count <= 0
        (5, 0, -1),
        (0, 0, 1),  # capacity <= 0
        (5, -1, 1),  # used < 0
        (5, 6, 1),  # used > capacity
    ],
)
def test_assert_reservable_raises_invalid(
    capacity: int, used: int, count: int
) -> None:
    """参数或数据非法 → SlotInvalidError，消息含三个数值。"""
    with pytest.raises(SlotInvalidError) as excinfo:
        assert_reservable(capacity, used, count)
    message = str(excinfo.value)
    assert str(capacity) in message
    assert str(used) in message
    assert str(count) in message


def test_invalid_takes_precedence_over_not_reservable() -> None:
    """同时违反多条规则时，非法数据优先报 SlotInvalidError。"""
    with pytest.raises(SlotInvalidError):
        assert_reservable(5, 6, 10)


# ------------------------------------------------------------- 异常继承结构


def test_error_hierarchy() -> None:
    assert issubclass(SlotInvalidError, SlotError)
    assert issubclass(SlotNotReservableError, SlotError)
    assert issubclass(SlotError, Exception)


def test_both_errors_are_slot_error() -> None:
    with pytest.raises(SlotError):
        assert_reservable(5, 3, 3)
    with pytest.raises(SlotError):
        assert_reservable(5, 0, 0)


def test_error_carries_context() -> None:
    with pytest.raises(SlotNotReservableError) as excinfo:
        assert_reservable(10, 8, 5)
    error = excinfo.value
    assert error.capacity == 10
    assert error.used == 8
    assert error.count == 5
    message = str(error)
    assert "10" in message
    assert "8" in message
    assert "5" in message
