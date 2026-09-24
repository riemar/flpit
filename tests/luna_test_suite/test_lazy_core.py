from __future__ import annotations

import pytest

import flp
from flp import FlpIt


class TrackedIterable:
    def __init__(self, values):
        self.values = list(values)
        self.iterations = 0
        self.yields = 0

    def __iter__(self):
        self.iterations += 1
        for value in self.values:
            self.yields += 1
            yield value


def test_where_is_deferred() -> None:
    seen = []

    query = flp.it([1, 2, 3]).where(lambda x: seen.append(x) or x > 1)
    assert seen == []
    assert list(query) == [2, 3]
    assert seen == [1, 2, 3]


def test_select_is_deferred() -> None:
    seen = []
    query = flp.it([1, 2]).select(lambda x: seen.append(x) or x * 10)
    assert seen == []
    assert list(query) == [10, 20]
    assert seen == [1, 2]


def test_select_many_is_deferred() -> None:
    seen = []
    query = flp.it([1, 2]).select_many(lambda x: seen.append(x) or [x, x + 10])
    assert seen == []
    assert list(query) == [1, 11, 2, 12]
    assert seen == [1, 2]


def test_append_is_deferred() -> None:
    source = TrackedIterable([1, 2])
    query = flp.it(source).append(3)
    assert source.iterations == 0
    assert list(query) == [1, 2, 3]
    assert source.iterations == 1


def test_prepend_is_deferred() -> None:
    source = TrackedIterable([2, 3])
    query = flp.it(source).prepend(1)
    assert source.iterations == 0
    assert list(query) == [1, 2, 3]
    assert source.iterations == 1


def test_concat_is_deferred() -> None:
    left = TrackedIterable([1, 2])
    right = TrackedIterable([3, 4])
    query = flp.it(left).concat(right)
    assert left.iterations == 0
    assert right.iterations == 0
    assert list(query) == [1, 2, 3, 4]
    assert left.iterations == 1
    assert right.iterations == 1


def test_take_does_not_evaluate_more_than_requested() -> None:
    source = TrackedIterable([1, 2, 3, 4, 5])
    query = flp.it(source).take(2)
    assert list(query) == [1, 2]
    assert source.yields == 2


def test_take_zero_is_empty_and_deferred() -> None:
    source = TrackedIterable([1, 2, 3])
    assert list(flp.it(source).take(0)) == []
    assert source.iterations == 0
    assert source.yields == 0


def test_take_negative_is_empty_and_deferred() -> None:
    source = TrackedIterable([1, 2, 3])
    assert list(flp.it(source).take(-1)) == []
    assert source.iterations == 0
    assert source.yields == 0


def test_pipeline_can_be_enumerated_twice_for_reiterable_source() -> None:
    query = flp.it([1, 2, 3]).where(lambda x: x > 1).select(lambda x: x * 2)
    assert list(query) == [4, 6]
    assert list(query) == [4, 6]


def test_one_shot_iterator_remains_one_shot() -> None:
    source = iter([1, 2, 3])
    query = flp.it(source).select(lambda x: x * 2)
    assert list(query) == [2, 4, 6]
    assert list(query) == []


def test_append_to_one_shot_iterator_is_one_shot() -> None:
    source = iter([1, 2])
    query = flp.it(source).append(3)
    assert list(query) == [1, 2, 3]
    assert list(query) == [3]


def test_concat_order_is_preserved() -> None:
    assert list(flp.it([1, 2]).concat([3, 4])) == [1, 2, 3, 4]


def test_select_many_preserves_nested_iteration_order() -> None:
    assert list(flp.it([[1, 2], [], [3], [4, 5]]).select_many(lambda xs: xs)) == [1, 2, 3, 4, 5]


def test_select_many_accepts_generators() -> None:
    result = list(flp.it([1, 2]).select_many(lambda x: (y for y in range(x))))
    assert result == [0, 0, 1]


def test_select_propagates_callback_exception() -> None:
    def fail(x):
        if x == 2:
            raise RuntimeError(f"bad {x}")
        return x

    with pytest.raises(RuntimeError, match="bad 2"):
        list(flp.it([1, 2, 3]).select(fail))


def test_where_propagates_callback_exception() -> None:
    def fail(x):
        if x == 2:
            raise LookupError(f"bad {x}")
        return True

    with pytest.raises(LookupError, match="bad 2"):
        list(flp.it([1, 2, 3]).where(fail))

