from __future__ import annotations

import pytest

from flpit import flp, FlpList, OrderedIt, EmptySequenceError


def test_flplist_to_list_returns_shallow_independent_copy() -> None:
    original = FlpList([1, 2])
    copied = original.to_list()
    assert isinstance(copied, FlpList)
    assert copied == original
    copied.append(3)
    assert original == [1, 2]


def test_flplist_append_linq_is_lazy_and_does_not_mutate() -> None:
    original = FlpList([1, 2])
    query = original.append_linq(3)
    assert isinstance(query, flp.FlpIt)
    assert original == [1, 2]
    assert list(query) == [1, 2, 3]


def test_flplist_prepend_is_lazy_and_does_not_mutate() -> None:
    original = FlpList([2, 3])
    query = original.prepend(1)
    assert isinstance(query, flp.FlpIt)
    assert original == [2, 3]
    assert list(query) == [1, 2, 3]


def test_flplist_as_type_returns_same_instance() -> None:
    original = FlpList([1, 2])
    assert original.as_type(str) is original


def test_flplist_select_wrapper() -> None:
    assert list(FlpList([1, 2, 3]).select(lambda x: x * 2)) == [2, 4, 6]


def test_flplist_select_many_wrapper() -> None:
    assert list(FlpList([1, 2]).select_many(lambda x: [x, x + 10])) == [1, 11, 2, 12]


def test_flplist_take_wrapper() -> None:
    assert list(FlpList([1, 2, 3]).take(2)) == [1, 2]


def test_flplist_cast_wrapper() -> None:
    assert list(FlpList([1, 2]).cast(int)) == [1, 2]


def test_flplist_of_type_wrapper() -> None:
    assert list(FlpList([1, "x", 2]).of_type(int)) == [1, 2]


def test_flplist_distinct_wrapper() -> None:
    assert list(FlpList([1, 1, 2]).distinct()) == [1, 2]


def test_flplist_distinct_by_wrapper() -> None:
    rows = [("a", 1), ("b", 1), ("c", 2)]
    assert list(FlpList(rows).distinct_by(lambda row: row[1])) == [rows[0], rows[2]]


def test_flplist_zip_wrapper() -> None:
    assert list(FlpList([1, 2]).zip([10, 20])) == [(1, 10), (2, 20)]


def test_flplist_zip_wrapper_with_selector() -> None:
    assert list(FlpList([1, 2]).zip([10, 20], lambda a, b: a + b)) == [11, 22]


def test_flplist_chunk_wrapper() -> None:
    chunks = list(FlpList([1, 2, 3]).chunk(2))
    assert [list(chunk) for chunk in chunks] == [[1, 2], [3]]


def test_flplist_order_by_wrapper() -> None:
    query = FlpList([3, 1, 2]).order_by(lambda x: x)
    assert isinstance(query, OrderedIt)
    assert list(query) == [1, 2, 3]


def test_flplist_order_by_descending_wrapper() -> None:
    assert list(FlpList([3, 1, 2]).order_by_descending(lambda x: x)) == [3, 2, 1]


def test_flplist_group_by_wrapper() -> None:
    groups = list(FlpList([1, 2, 3]).group_by(lambda x: x % 2))
    assert [(group.key, list(group)) for group in groups] == [(1, [1, 3]), (0, [2])]


def test_flplist_aggregate_without_seed() -> None:
    assert FlpList([1, 2, 3]).aggregate(lambda a, b: a + b) == 6


def test_flplist_aggregate_with_seed() -> None:
    assert FlpList([1, 2, 3]).aggregate(lambda a, b: a + b, 10) == 16


def test_flplist_aggregate_empty_without_seed_raises() -> None:
    with pytest.raises(EmptySequenceError):
        FlpList([]).aggregate(lambda a, b: a + b)


def test_flplist_min_max_and_by_variants() -> None:
    rows = [("a", 3), ("b", 1), ("c", 2)]
    values = FlpList([3, 1, 2])
    assert values.min() == 1
    assert values.max() == 3
    assert FlpList(rows).min_by(lambda x: x[1]) == rows[1]
    assert FlpList(rows).max_by(lambda x: x[1]) == rows[0]


@pytest.mark.parametrize("method", ["min", "max"])
def test_flplist_min_max_empty_uses_empty_sequence_error(method) -> None:
    with pytest.raises(EmptySequenceError, match="Sequence contains no elements"):
        getattr(FlpList([]), method)()


@pytest.mark.parametrize("method", ["min_by", "max_by"])
def test_flplist_min_max_by_empty_uses_empty_sequence_error(method) -> None:
    with pytest.raises(EmptySequenceError, match="Sequence contains no elements"):
        getattr(FlpList([]), method)(lambda x: x)


def test_flplist_min_does_not_relabel_value_error_from_comparison() -> None:
    class Broken:
        def __lt__(self, other):
            raise ValueError("comparison broke")

    with pytest.raises(ValueError, match="comparison broke"):
        FlpList([Broken(), Broken()]).min()


def test_flplist_sum_and_average_wrappers() -> None:
    values = FlpList([1, 2, 3])
    assert values.sum() == 6
    assert values.average() == 2.0
    rows = [("a", 1), ("b", 5)]
    assert FlpList(rows).sum(lambda x: x[1]) == 6
    assert FlpList(rows).average(lambda x: x[1]) == 3.0


def test_flplist_count_no_argument_is_length() -> None:
    assert FlpList([1, 1, 2]).count() == 3


def test_flplist_count_exact_value() -> None:
    assert FlpList([1, 1, 2]).count(1) == 2


def test_flplist_count_predicate() -> None:
    assert FlpList([1, 2, 3, 4]).count(lambda x: x % 2 == 0) == 2


def test_flplist_count_exact_callable_value_is_ambiguous_and_currently_treated_as_predicate() -> None:
    callable_item = lambda x: x
    values = FlpList([callable_item, callable_item])
    # This exposes the API ambiguity: count(callable) is always interpreted as a predicate.
    assert values.count(callable_item) == 2


def test_flplist_element_at() -> None:
    values = FlpList([10, 20, 30])
    assert values.element_at(1) == 20
    with pytest.raises(IndexError, match="Index out of range"):
        values.element_at(3)
    with pytest.raises(IndexError, match="Index out of range"):
        values.element_at(-1)


def test_flplist_first_variants() -> None:
    values = FlpList([1, 2, 3])
    assert values.first() == 1
    assert values.first(lambda x: x > 1) == 2
    assert values.first_or_default(99, lambda x: x > 9) == 99


def test_flplist_first_or_default_propagates_non_value_error() -> None:
    def fail(_):
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        FlpList([1]).first_or_default(99, fail)


def test_flplist_single_variants() -> None:
    assert FlpList([2]).single() == 2
    assert FlpList([1, 2, 3]).single(lambda x: x == 2) == 2

