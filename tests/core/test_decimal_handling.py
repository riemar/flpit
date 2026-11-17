"""sum()/average() over Decimals: .NET-style range and rounding without touching the caller's context."""

from __future__ import annotations

import decimal
from decimal import Decimal

import pytest

from flpit.flp import it

MAX = Decimal("79228162514264337593543950335")  # System.Decimal.MaxValue
MIN = Decimal("-79228162514264337593543950335")  # System.Decimal.MaxValue

def test_global_context_is_not_modified_even_when_the_sum_raises() -> None:
    before = decimal.getcontext().copy()
    with pytest.raises(OverflowError):
        it([MAX, MAX]).sum()
    after = decimal.getcontext()
    assert (after.prec, after.rounding, dict(after.traps)) == (before.prec, before.rounding, dict(before.traps))


def test_sum_beyond_the_precision_ceiling_raises_overflow() -> None:
    with pytest.raises(OverflowError, match="System.OverflowException"):
        it([MAX, MAX]).sum()


def test_SUM_intermediate_overflow() -> None:
    with pytest.raises(OverflowError, match="System.OverflowException"):
        it([MAX, MAX, MIN]).sum()


def test_sum_below_the_negative_ceiling_raises_overflow() -> None:
    with pytest.raises(OverflowError, match="System.OverflowException"):
        it([MIN, MIN]).sum()


def test_sum_at_exactly_decimal_max_is_fine() -> None:
    assert it([MAX, Decimal(0)]).sum() == MAX


def test_ceiling_is_ten_to_the_precision_not_a_separate_constant() -> None:
    # Default precision is 29 digits: anything that still fits in 29 digits is fine, 1e29 is not.
    assert it([MAX, Decimal(1)]).sum() == Decimal("79228162514264337593543950336")
    assert it([Decimal("9" * 29), Decimal(0)]).sum() == Decimal("9" * 29)
    with pytest.raises(OverflowError, match="System.OverflowException"):
        it([Decimal("1e29"), Decimal(0)]).sum()


def test_average_overflows_like_sum() -> None:
    with pytest.raises(OverflowError, match="System.OverflowException"):
        it([MAX, MAX]).average()


def test_average_intermediate_overflow() -> None:
    with pytest.raises(OverflowError, match="System.OverflowException"):
        it([MAX, MAX, MIN]).average()


def test_callers_own_decimal_overflow_is_not_converted() -> None:
    with pytest.raises(decimal.Overflow):
        it([Decimal(10)]).sum(lambda d: d * Decimal("1e999999"))


def test_sum_needing_more_than_29_digits_rounds_instead_of_raising() -> None:
    values = [Decimal("1234567890123456789012345678.9"), Decimal("0.11")]
    assert it(values).sum() == Decimal("1234567890123456789012345679.0")
    assert it(values).average() == Decimal("617283945061728394506172839.5")


def test_decimal_appearing_after_ints_is_summed_in_the_net_context() -> None:
    assert it([1, 2, Decimal("0.5")]).sum() == Decimal("3.5")
    with pytest.raises(OverflowError):
        it([1, Decimal("1e29")]).sum()


def test_float_and_decimal_do_not_mix() -> None:
    with pytest.raises(TypeError):
        it([1.5, Decimal(1)]).sum()
    with pytest.raises(TypeError):
        it([Decimal(1), 1.5]).sum()


def test_none_items_are_skipped_and_not_counted() -> None:
    assert it([None, Decimal(1), None, Decimal(3)]).sum() == Decimal(4)
    assert it([None, Decimal(1), None, Decimal(3)]).average() == Decimal(2)
    assert it([None, None]).average() is None
    assert it([]).sum() == 0


def test_invalid_operations_still_raise() -> None:
    with pytest.raises(decimal.InvalidOperation):
        it([Decimal("Infinity"), Decimal("-Infinity")]).sum()


def test_sum_pulls_and_projects_one_item_at_a_time() -> None:
    log: list[str] = []

    def source():
        for i in range(3):
            log.append(f"pull{i}")
            yield Decimal(i)

    it(source()).sum(lambda value: (log.append(f"select{int(value)}"), value)[1])

    assert log == ["pull0", "select0", "pull1", "select1", "pull2", "select2"]


# --- rounding inside the caller's own code (lazy, so it also runs while sum()/average() iterate) ---


def test_sum_selector_may_divide_inexactly() -> None:
    # .NET: new[] { 1m, 2m }.Sum(d => d / 3) == 1.0000000000000000000000000000
    assert it([Decimal(1), Decimal(2)]).sum(lambda d: d / 3) == Decimal(1)


def test_upstream_select_may_divide_inexactly_before_sum() -> None:
    # The division sits in an earlier select(); the query is lazy, so it runs inside sum().
    assert it([Decimal(1), Decimal(2)]).select(lambda d: d / 3).sum() == Decimal(1)


def test_average_selector_may_divide_inexactly() -> None:
    # .NET: new[] { 1m, 2m }.Average(d => d / 3) == 0.5
    assert it([Decimal(1), Decimal(2)]).average(lambda d: d / 3) == Decimal("0.5")


def test_average_with_a_non_terminating_result_rounds() -> None:
    # .NET: new[] { 1m, 1m, 2m }.Average() == 1.3333333333333333333333333333
    assert it([Decimal(1), Decimal(1), Decimal(2)]).average() == Decimal("1.3333333333333333333333333333")


def test_average_of_ints_through_a_decimal_selector_rounds() -> None:
    # .NET: new[] { 1, 1, 2 }.Average(x => (decimal)x) == 1.3333333333333333333333333333
    assert it([1, 1, 2]).average(lambda x: Decimal(x)) == Decimal("1.3333333333333333333333333333")


def test_sum_that_only_needs_rounding_is_not_an_overflow() -> None:
    # The exact sum needs 41 significant digits, a .NET decimal holds 28-29. Rounded, no exception.
    assert it([Decimal("1e20"), Decimal("1e-20")]).sum() == Decimal("1e20")


# --- precision: at least 29 digits, more when the caller's own context asks for more ---


def test_caller_precision_above_29_is_kept() -> None:
    value = Decimal("1.2345678901234567890123456789012345")
    with decimal.localcontext() as context:
        context.prec = 50
        assert it([value, Decimal(1)]).sum() == Decimal("2.2345678901234567890123456789012345")
        assert it([value, Decimal(1)]).average() == Decimal("1.11728394506172839450617283945061725")
        assert context.prec == 50


def test_caller_precision_below_29_is_raised_to_29() -> None:
    with decimal.localcontext() as context:
        context.prec = 10
        values = [Decimal("1234567890123456789012345678.9"), Decimal("0.11")]
        assert it(values).sum() == Decimal("1234567890123456789012345679.0")
        assert context.prec == 10


def test_ceiling_follows_a_higher_caller_precision() -> None:
    with decimal.localcontext() as context:
        context.prec = 50
        assert it([Decimal("1e29"), Decimal(0)]).sum() == Decimal("1e29")
        assert it([Decimal("1e40"), Decimal(1)]).sum() == Decimal("10000000000000000000000000000000000000001")
        with pytest.raises(OverflowError, match="System.OverflowException"):
            it([Decimal("1e50"), Decimal(0)]).sum()
