from __future__ import annotations

import math

import pytest

import flp
from flp import FlpList


@pytest.mark.parametrize(
    "values",
    [[], [1], [1, 2], [1, 2, 3], list(range(20))],
)
def test_distinct_matches_python_dict_order_for_hashable_values(values) -> None:
    expected = list(dict.fromkeys(values))
    assert list(flp.it(values).distinct()) == expected


@pytest.mark.parametrize("value", [None, 0, False, "", object()])
def test_repeat_preserves_identity_for_singletons(value) -> None:
    result = list(flp.repeat(value, 1))
    assert len(result) == 1
    if value is None or isinstance(value, object):
        assert result[0] is value


def test_where_all_false() -> None:
    assert list(flp.it([1, 2, 3]).where(lambda _: False)) == []


def test_where_all_true() -> None:
    values = [1, 2, 3]
    assert list(flp.it(values).where(lambda _: True)) == values


def test_select_identity() -> None:
    values = [1, 2, 3]
    assert list(flp.it(values).select(lambda x: x)) == values


def test_select_changes_type() -> None:
    result = flp.it([1, 2, 3]).select(str)
    assert list(result) == ["1", "2", "3"]


def test_select_many_with_empty_inner_sequences() -> None:
    assert list(flp.it([[], [1], [], [2, 3]]).select_many(lambda x: x)) == [1, 2, 3]


def test_append_then_prepend_then_concat() -> None:
    result = flp.it([2]).append(3).prepend(1).concat([4, 5])
    assert list(result) == [1, 2, 3, 4, 5]


def test_multiple_lazy_operations_compose_in_expected_order() -> None:
    result = (
        flp.it(range(10))
        .where(lambda x: x % 2 == 0)
        .select(lambda x: x + 1)
        .where(lambda x: x > 4)
        .take(2)
    )
    assert list(result) == [5, 7]


def test_group_by_after_projection() -> None:
    result = (
        flp.it([1, 2, 3, 4])
        .select(lambda x: (x % 2, x * 10))
        .group_by(lambda pair: pair[0])
        .select(lambda group: (group.key, list(group)))
        .to_list()
    )
    assert result == [(1, [(1, 10), (1, 30)]), (0, [(0, 20), (0, 40)])]


def test_order_then_take_only_materializes_ordered_source_once() -> None:
    calls = []
    query = flp.it([5, 1, 4, 2, 3]).order_by(lambda x: calls.append(x) or x).take(2)
    assert list(query) == [1, 2]
    assert calls == [5, 1, 4, 2, 3]


def test_order_then_select_is_repeatable() -> None:
    query = flp.it([3, 1, 2]).order_by(lambda x: x).select(lambda x: x * 2)
    assert list(query) == [2, 4, 6]
    assert list(query) == [2, 4, 6]


def test_grouping_can_be_selected_without_materializing_outer_query() -> None:
    query = flp.it([1, 2, 3]).group_by(lambda x: x % 2).select(lambda g: g.key)
    assert list(query) == [1, 0]


def test_flplist_add_range_accepts_flpit() -> None:
    result = FlpList([1])
    result.add_range(flp.it([2, 3]))
    assert result == [1, 2, 3]


def test_average_accepts_decimal_like_float_convertible_values() -> None:
    class Number:
        def __init__(self, value):
            self.value = value

        def __float__(self):
            return float(self.value)

    assert flp.it([Number(1), Number(3)]).average() == 2.0


def test_sum_selector_can_return_ints_from_objects() -> None:
    class Number:
        def __init__(self, value):
            self.value = value

    assert flp.it([Number(1), Number(2)]).sum(lambda x: x.value) == 3


def test_element_at_does_not_accept_negative_index() -> None:
    with pytest.raises(IndexError):
        flp.it([1, 2, 3]).element_at(-1)


def test_empty_materialization_returns_empty_flplist() -> None:
    result = flp.it([]).to_list()
    assert isinstance(result, FlpList)
    assert result == []


def test_count_with_generator_predicate_results() -> None:
    assert flp.it(range(100)).count(lambda x: x % 10 == 0) == 10


def test_large_simple_pipeline_completes() -> None:
    result = (
        flp.it(range(1000))
        .where(lambda x: x % 3 == 0)
        .select(lambda x: x * x)
        .take(50)
        .to_list()
    )
    assert len(result) == 50
    assert result[0] == 0
    assert result[-1] == (3 * 49) ** 2


def test_ordering_handles_negative_and_duplicate_numbers() -> None:
    assert list(flp.it([0, -1, -1, 2, -3]).order_by(lambda x: x)) == [-3, -1, -1, 0, 2]


def test_average_of_boolean_values_uses_numeric_conversion() -> None:
    assert math.isclose(flp.it([True, False, True]).average(), 2 / 3)

