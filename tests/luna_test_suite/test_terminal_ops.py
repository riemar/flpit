from __future__ import annotations

import math

import pytest

import flp
from flp.core.linq import EmptySequenceError, NoMatchError, MultipleMatchesError, MultipleElementsError


@pytest.mark.parametrize(
    "values, expected",
    [([3, 1, 2], 1), ([1], 1), ([-3, -1, -2], -3)],
)
def test_min(values, expected) -> None:
    assert flp.it(values).min() == expected


@pytest.mark.parametrize(
    "values, expected",
    [([3, 1, 2], 3), ([1], 1), ([-3, -1, -2], -1)],
)
def test_max(values, expected) -> None:
    assert flp.it(values).max() == expected


@pytest.mark.parametrize("method", ["min", "max"])
def test_min_max_empty_raise_empty_sequence(method) -> None:
    with pytest.raises(EmptySequenceError, match="no elements"):
        getattr(flp.it([]), method)()


def test_min_by_returns_original_item() -> None:
    rows = [("a", 3), ("b", 1), ("c", 2)]
    assert flp.it(rows).min_by(lambda row: row[1]) == ("b", 1)


def test_max_by_returns_original_item() -> None:
    rows = [("a", 3), ("b", 1), ("c", 2)]
    assert flp.it(rows).max_by(lambda row: row[1]) == ("a", 3)


def test_min_by_empty_raises() -> None:
    with pytest.raises(EmptySequenceError):
        flp.it([]).min_by(lambda x: x)


def test_max_by_empty_raises() -> None:
    with pytest.raises(EmptySequenceError):
        flp.it([]).max_by(lambda x: x)


def test_average_numbers() -> None:
    assert flp.it([1, 2, 3]).average() == 2.0
    assert flp.it([1, 2, 3]).avg() == 2.0


def test_average_works_with_int_and_float_mix() -> None:
    assert math.isclose(flp.it([1, 2.5, 4]).average(), 2.5)


def test_average_selector() -> None:
    rows = [{"x": 1}, {"x": 5}, {"x": 3}]
    assert flp.it(rows).average(lambda row: row["x"]) == 3.0


def test_average_by() -> None:
    rows = [("a", 1), ("b", 5)]
    assert flp.it(rows).average_by(lambda row: row[1]) == 3.0
    assert flp.it(rows).avg_by(lambda row: row[1]) == 3.0


def test_average_empty_raises() -> None:
    with pytest.raises(EmptySequenceError):
        flp.it([]).average()


def test_average_by_empty_raises() -> None:
    with pytest.raises(EmptySequenceError):
        flp.it([]).average_by(lambda x: x)


def test_average_callback_exception_propagates() -> None:
    def fail(value):
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        flp.it([1, 2]).average(fail)


def test_average_by_callback_exception_propagates() -> None:
    with pytest.raises(RuntimeError, match="boom"):
        flp.it([1, 2]).average_by(lambda _: (_ for _ in ()).throw(RuntimeError("boom")))


def test_sum_numbers() -> None:
    assert flp.it([1, 2, 3]).sum() == 6


def test_sum_empty_is_zero() -> None:
    assert flp.it([]).sum() == 0


def test_sum_selector() -> None:
    rows = [{"x": 2}, {"x": 4}, {"x": 8}]
    assert flp.it(rows).sum(lambda row: row["x"]) == 14


def test_sum_preserves_builtin_numeric_behavior() -> None:
    assert flp.it([1.5, 2.5]).sum() == 4.0


def test_sum_callback_exception_propagates() -> None:
    with pytest.raises(RuntimeError, match="boom"):
        flp.it([1, 2]).sum(lambda _: (_ for _ in ()).throw(RuntimeError("boom")))


def test_count_without_predicate() -> None:
    assert flp.it([1, 2, 3]).count() == 3


def test_count_with_predicate() -> None:
    assert flp.it([1, 2, 3, 4]).count(lambda x: x % 2 == 0) == 2


def test_count_empty() -> None:
    assert flp.it([]).count() == 0


def test_count_propagates_predicate_exception() -> None:
    with pytest.raises(RuntimeError, match="boom"):
        flp.it([1, 2]).count(lambda _: (_ for _ in ()).throw(RuntimeError("boom")))


@pytest.mark.parametrize("index, expected", [(0, 10), (1, 20), (2, 30)])
def test_element_at(index, expected) -> None:
    assert flp.it([10, 20, 30]).element_at(index) == expected


@pytest.mark.parametrize("index", [-1, 3, 999])
def test_element_at_out_of_range(index) -> None:
    with pytest.raises(IndexError, match="Index out of range"):
        flp.it([10, 20, 30]).element_at(index)


def test_first_without_predicate() -> None:
    assert flp.it([10, 20]).first() == 10


def test_first_with_predicate() -> None:
    assert flp.it([1, 2, 3]).first(lambda x: x > 1) == 2


def test_first_empty_raises() -> None:
    with pytest.raises(EmptySequenceError):
        flp.it([]).first()


def test_first_no_match_raises() -> None:
    with pytest.raises(NoMatchError):
        flp.it([1, 2]).first(lambda x: x > 10)


def test_first_or_default_returns_match() -> None:
    assert flp.it([1, 2, 3]).first_or_default(99, lambda x: x == 2) == 2


def test_first_or_default_returns_default_on_no_match() -> None:
    assert flp.it([1, 2, 3]).first_or_default(99, lambda x: x == 9) == 99


def test_first_or_default_returns_default_on_empty() -> None:
    assert flp.it([]).first_or_default(99) == 99


def test_single_without_predicate_requires_exactly_one() -> None:
    assert flp.it([42]).single() == 42


def test_single_empty_raises() -> None:
    with pytest.raises(EmptySequenceError):
        flp.it([]).single()


def test_single_multiple_raises(flp_type) -> None:
    with pytest.raises(MultipleElementsError):
        flp_type([1, 2]).single()


def test_single_predicate() -> None:
    assert flp.it([1, 2, 3]).single(lambda x: x == 2) == 2


def test_single_predicate_multiple_matches_raises() -> None:
    with pytest.raises(MultipleMatchesError):
        flp.it([1, 2, 2, 3]).single(lambda x: x == 2)


def test_to_list_materializes() -> None:
    query = flp.it([1, 2, 3]).select(lambda x: x * 10)
    result = query.to_list()
    assert isinstance(result, flp.FlpList)
    assert result == [10, 20, 30]

