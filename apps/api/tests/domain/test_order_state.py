"""订单状态机单测。

覆盖 12 个状态两两组合的全部 144 种流转，逐条核对状态机的判定结果。
本文件独立维护一份「期望流转表」，与被测实现互为对照——
若两边写岔了，测试会失败。
"""
from __future__ import annotations

from itertools import product

import pytest

from app.domain.order_state import (
    TERMINAL_STATUSES,
    OrderTransitionError,
    allowed_next_statuses,
    assert_transition,
    is_valid_transition,
)
from app.models.enums import OrderStatus

ALL_STATUSES: tuple[OrderStatus, ...] = tuple(OrderStatus)

# 期望流转表（独立于被测实现维护）
EXPECTED_TRANSITIONS: dict[OrderStatus, tuple[OrderStatus, ...]] = {
    OrderStatus.PENDING_PAY: (
        OrderStatus.PENDING_DISPATCH,
        OrderStatus.CANCELLED,
    ),
    OrderStatus.PENDING_DISPATCH: (
        OrderStatus.PENDING_ACCEPT,
        OrderStatus.REFUNDING,
    ),
    OrderStatus.PENDING_ACCEPT: (
        OrderStatus.ACCEPTED,
        OrderStatus.PENDING_DISPATCH,
        OrderStatus.REFUNDING,
    ),
    OrderStatus.ACCEPTED: (
        OrderStatus.IN_SERVICE,
        OrderStatus.REFUNDING,
    ),
    OrderStatus.IN_SERVICE: (OrderStatus.PENDING_CONFIRM,),
    OrderStatus.PENDING_CONFIRM: (OrderStatus.COMPLETED,),
    OrderStatus.COMPLETED: (OrderStatus.PENDING_SETTLE,),
    OrderStatus.PENDING_SETTLE: (OrderStatus.SETTLED,),
    OrderStatus.REFUNDING: (OrderStatus.REFUNDED,),
    OrderStatus.CANCELLED: (),
    OrderStatus.SETTLED: (),
    OrderStatus.REFUNDED: (),
}

EXPECTED_TERMINAL_STATUSES: frozenset[OrderStatus] = frozenset(
    {OrderStatus.CANCELLED, OrderStatus.SETTLED, OrderStatus.REFUNDED}
)

ALL_PAIRS: list[tuple[OrderStatus, OrderStatus]] = list(product(ALL_STATUSES, ALL_STATUSES))
LEGAL_PAIRS: list[tuple[OrderStatus, OrderStatus]] = [
    (from_status, to_status)
    for from_status, targets in EXPECTED_TRANSITIONS.items()
    for to_status in targets
]
ILLEGAL_PAIRS: list[tuple[OrderStatus, OrderStatus]] = [
    pair for pair in ALL_PAIRS if pair not in LEGAL_PAIRS
]


# --------------------------------------------------------------------------- 前置校验


def test_state_count_is_twelve() -> None:
    assert len(ALL_STATUSES) == 12
    assert len(ALL_PAIRS) == 144


def test_expected_table_covers_every_status() -> None:
    """期望流转表必须覆盖全部 12 个状态，不能漏键。"""
    assert set(EXPECTED_TRANSITIONS) == set(ALL_STATUSES)


def test_expected_table_only_references_known_statuses() -> None:
    """流转表里不得出现 12 个状态之外的取值。"""
    known = set(ALL_STATUSES)
    for targets in EXPECTED_TRANSITIONS.values():
        for target in targets:
            assert target in known


# ------------------------------------------------------- 144 种组合逐条断言


@pytest.mark.parametrize(
    ("from_status", "to_status"),
    ALL_PAIRS,
    ids=[f"{src.value}->{dst.value}" for src, dst in ALL_PAIRS],
)
def test_is_valid_transition_matches_table(
    from_status: OrderStatus, to_status: OrderStatus
) -> None:
    expected = to_status in EXPECTED_TRANSITIONS.get(from_status, ())
    assert is_valid_transition(from_status, to_status) is expected


@pytest.mark.parametrize(
    ("from_status", "to_status"),
    LEGAL_PAIRS,
    ids=[f"{src.value}->{dst.value}" for src, dst in LEGAL_PAIRS],
)
def test_assert_transition_accepts_legal_transition(
    from_status: OrderStatus, to_status: OrderStatus
) -> None:
    assert_transition(from_status, to_status)


@pytest.mark.parametrize(
    ("from_status", "to_status"),
    ILLEGAL_PAIRS,
    ids=[f"{src.value}->{dst.value}" for src, dst in ILLEGAL_PAIRS],
)
def test_assert_transition_rejects_illegal_transition(
    from_status: OrderStatus, to_status: OrderStatus
) -> None:
    with pytest.raises(OrderTransitionError):
        assert_transition(from_status, to_status)


# --------------------------------------------------- allowed_next_statuses


@pytest.mark.parametrize("status", ALL_STATUSES, ids=lambda s: s.value)
def test_allowed_next_statuses_matches_table(status: OrderStatus) -> None:
    assert allowed_next_statuses(status) == list(EXPECTED_TRANSITIONS.get(status, ()))


@pytest.mark.parametrize(
    "status", sorted(EXPECTED_TERMINAL_STATUSES, key=lambda s: s.value),
    ids=lambda s: s.value,
)
def test_terminal_statuses_have_empty_next_statuses(status: OrderStatus) -> None:
    """终态没有出边，返回空列表。"""
    assert allowed_next_statuses(status) == []
    assert is_valid_transition(status, status) is False


def test_terminal_status_set_matches_expectation() -> None:
    assert TERMINAL_STATUSES == EXPECTED_TERMINAL_STATUSES


def test_allowed_next_statuses_returns_independent_list() -> None:
    """返回的是新列表，调用方改动不会污染状态机。"""
    first = allowed_next_statuses(OrderStatus.PENDING_PAY)
    first.append(OrderStatus.SETTLED)
    assert allowed_next_statuses(OrderStatus.PENDING_PAY) == [
        OrderStatus.PENDING_DISPATCH,
        OrderStatus.CANCELLED,
    ]


# ------------------------------------------------------------- 自流转与错误信息


@pytest.mark.parametrize("status", ALL_STATUSES, ids=lambda s: s.value)
def test_self_transition_is_always_invalid(status: OrderStatus) -> None:
    """同状态到自身（ACCEPTED → ACCEPTED 等）一律非法。"""
    assert is_valid_transition(status, status) is False
    with pytest.raises(OrderTransitionError):
        assert_transition(status, status)


def test_transition_error_carries_both_statuses() -> None:
    with pytest.raises(OrderTransitionError) as excinfo:
        assert_transition(OrderStatus.ACCEPTED, OrderStatus.ACCEPTED)
    error = excinfo.value
    assert error.from_status is OrderStatus.ACCEPTED
    assert error.to_status is OrderStatus.ACCEPTED
    assert "ACCEPTED" in str(error)


def test_unknown_status_is_rejected_not_allowed() -> None:
    """表外取值不得被默认放行。"""

    class FakeStatus(str):
        pass

    assert is_valid_transition(FakeStatus("NOT_A_STATUS"), OrderStatus.SETTLED) is False
    assert is_valid_transition(OrderStatus.PENDING_PAY, FakeStatus("NOT_A_STATUS")) is False
    assert allowed_next_statuses(FakeStatus("NOT_A_STATUS")) == []
    with pytest.raises(OrderTransitionError):
        assert_transition(OrderStatus.PENDING_PAY, FakeStatus("NOT_A_STATUS"))
