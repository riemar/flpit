from __future__ import annotations

import pytest

import flp


class ClosableIterator:
    def __init__(self, values):
        self.values = iter(values)
        self.closed = False

    def __iter__(self):
        return self

    def __next__(self):
        if self.closed:
            raise StopIteration
        return next(self.values)

    def close(self):
        self.closed = True


def test_take_does_not_close_upstream_on_normal_limit() -> None:
    source = ClosableIterator([1, 2, 3, 4])
    assert list(flp.it(source).take(2)) == [1, 2]
    assert source.closed is False


def test_full_iteration_does_not_require_close_method() -> None:
    source = ClosableIterator([1, 2])
    assert list(flp.it(source)) == [1, 2]


def test_select_many_does_not_eagerly_consume_selector_results() -> None:
    events = []

    def selector(value):
        events.append(("selector", value))
        return iter((value, value + 10))

    query = flp.it([1, 2]).select_many(selector)
    assert events == []
    iterator = iter(query)
    assert next(iterator) == 1
    assert events == [("selector", 1)]
    assert next(iterator) == 11
    assert events == [("selector", 1)]
    assert next(iterator) == 2


def test_where_does_not_evaluate_past_consumed_item() -> None:
    seen = []
    iterator = iter(flp.it([1, 2, 3]).where(lambda x: seen.append(x) or x > 1))
    assert next(iterator) == 2
    assert seen == [1, 2]


def test_select_does_not_evaluate_past_consumed_item() -> None:
    seen = []
    iterator = iter(flp.it([1, 2, 3]).select(lambda x: seen.append(x) or x * 2))
    assert next(iterator) == 2
    assert seen == [1]


def test_distinct_stops_source_when_consumer_stops() -> None:
    seen = []

    def source():
        for value in [1, 1, 2, 3, 4]:
            seen.append(value)
            yield value

    iterator = iter(flp.it(source()).distinct())
    assert next(iterator) == 1
    assert next(iterator) == 2
    assert seen == [1, 1, 2]


def test_chunk_stops_source_at_chunk_boundary_when_consumer_stops() -> None:
    seen = []

    def source():
        for value in range(10):
            seen.append(value)
            yield value

    iterator = iter(flp.it(source()).chunk(3))
    first = next(iterator)
    assert list(first) == [0, 1, 2]
    assert seen == [0, 1, 2]


@pytest.mark.parametrize("count", [1, 2, 5])
def test_take_consumes_at_most_count_elements(count: int) -> None:
    seen = []

    def source():
        for value in range(100):
            seen.append(value)
            yield value

    assert list(flp.it(source()).take(count)) == list(range(count))
    assert seen == list(range(count))

