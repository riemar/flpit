from __future__ import annotations

import pytest

import flp
from flp import FlpList, Grouping
from flp.core.linq import EmptySequenceError


def test_chunk_splits_exact_multiple() -> None:
    result = list(flp.it(range(6)).chunk(2))
    assert [list(chunk) for chunk in result] == [[0, 1], [2, 3], [4, 5]]
    assert all(isinstance(chunk, FlpList) for chunk in result)


def test_chunk_keeps_remainder() -> None:
    result = list(flp.it(range(5)).chunk(2))
    assert [list(chunk) for chunk in result] == [[0, 1], [2, 3], [4]]


def test_chunk_one_yields_singleton_lists() -> None:
    result = list(flp.it([1, 2, 3]).chunk(1))
    assert [list(chunk) for chunk in result] == [[1], [2], [3]]


def test_chunk_empty_source_is_empty() -> None:
    assert list(flp.it([]).chunk(3)) == []


@pytest.mark.parametrize("size", [0, -1, -10])
def test_chunk_rejects_non_positive_sizes(size: int) -> None:
    with pytest.raises(ValueError, match="greater than 0"):
        flp.it([1, 2]).chunk(size)


def test_chunk_is_deferred_for_valid_size() -> None:
    seen = []

    def source():
        seen.append("iterated")
        yield from [1, 2, 3]

    query = flp.it(source()).chunk(2)
    assert seen == []
    assert [list(x) for x in query] == [[1, 2], [3]]
    assert seen == ["iterated"]


def test_group_by_returns_grouping_objects() -> None:
    groups = list(flp.it([1, 2, 3, 4]).group_by(lambda x: x % 2))
    assert all(isinstance(group, Grouping) for group in groups)
    assert [group.key for group in groups] == [1, 0]
    assert [list(group) for group in groups] == [[1, 3], [2, 4]]


def test_group_by_preserves_first_key_order() -> None:
    rows = [("b", 1), ("a", 2), ("b", 3), ("a", 4)]
    groups = list(flp.it(rows).group_by(lambda row: row[0]))
    assert [g.key for g in groups] == ["b", "a"]


def test_grouping_is_reiterable() -> None:
    grouping = list(flp.it([1, 3, 5]).group_by(lambda x: 1))[0]
    assert list(grouping) == [1, 3, 5]
    assert list(grouping) == [1, 3, 5]


def test_grouping_repr_contains_key_and_elements() -> None:
    grouping = list(flp.it([1, 2]).group_by(lambda _: "x"))[0]
    text = repr(grouping)
    assert "Grouping" in text
    assert "'x'" in text
    assert "[1, 2]" in text


def test_grouping_equality_compares_key_and_elements() -> None:
    left = Grouping("x", [1, 2])
    equal = Grouping("x", [1, 2])
    diff_key = Grouping("y", [1, 2])
    diff_items = Grouping("x", [2, 1])
    assert left == equal
    assert left != diff_key
    assert left != diff_items
    assert left != object()


def test_aggregate_without_seed_reduces_from_first_element() -> None:
    assert flp.it([1, 2, 3, 4]).aggregate(lambda a, b: a + b) == 10


def test_aggregate_with_seed_uses_seed_even_for_empty_source() -> None:
    assert flp.it([]).aggregate(lambda a, b: a + b, 10) == 10


def test_aggregate_with_seed_applies_function_left_to_right() -> None:
    assert flp.it([1, 2, 3]).aggregate(lambda a, b: a * 10 + b, 0) == 123


def test_aggregate_without_seed_on_empty_raises() -> None:
    with pytest.raises(EmptySequenceError, match="no elements"):
        flp.it([]).aggregate(lambda a, b: a + b)


def test_aggregate_propagates_user_exception() -> None:
    def fail(a, b):
        raise RuntimeError(f"bad {a} {b}")

    with pytest.raises(RuntimeError, match="bad 1 2"):
        flp.it([1, 2]).aggregate(fail)

