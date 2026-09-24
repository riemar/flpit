from __future__ import annotations

import threading
import time

import pytest

import flp
from flp import OrderedIt


def test_order_by_returns_ordered_it() -> None:
    result = flp.it([3, 1, 2]).order_by(lambda x: x)
    assert isinstance(result, OrderedIt)


def test_order_by_ascending() -> None:
    assert list(flp.it([3, 1, 2])) == [3, 1, 2]
    assert list(flp.it([3, 1, 2]).order_by(lambda x: x)) == [1, 2, 3]


def test_order_by_descending() -> None:
    assert list(flp.it([3, 1, 2]).order_by_descending(lambda x: x)) == [3, 2, 1]


def test_order_by_is_lazy_until_iteration() -> None:
    calls = []
    query = flp.it([3, 1, 2]).order_by(lambda x: calls.append(x) or x)
    assert calls == []
    assert list(query) == [1, 2, 3]
    assert sorted(calls) == [1, 2, 3]


def test_order_by_caches_result_after_first_successful_iteration() -> None:
    calls = []
    query = flp.it([3, 1, 2]).order_by(lambda x: calls.append(x) or x)
    assert list(query) == [1, 2, 3]
    first_call_count = len(calls)
    assert list(query) == [1, 2, 3]
    assert len(calls) == first_call_count


def test_order_by_cache_survives_mutation_of_reiterable_source() -> None:
    source = [3, 1, 2]
    query = flp.it(source).order_by(lambda x: x)
    assert list(query) == [1, 2, 3]
    source[:] = [99, 98]
    assert list(query) == [1, 2, 3]


def test_order_by_consumes_one_shot_source_once_and_then_reuses_cache() -> None:
    source = iter([3, 1, 2])
    query = flp.it(source).order_by(lambda x: x)
    assert list(query) == [1, 2, 3]
    assert list(query) == [1, 2, 3]


def test_order_by_is_stable_for_equal_keys() -> None:
    rows = [("first", 1), ("second", 1), ("third", 2), ("fourth", 1)]
    result = list(flp.it(rows).order_by(lambda row: row[1]))
    assert result == [rows[0], rows[1], rows[3], rows[2]]


def test_then_by_adds_secondary_sort_key() -> None:
    rows = [("a", 2), ("b", 1), ("c", 2), ("d", 1)]
    query = flp.it(rows).order_by(lambda row: row[1]).then_by(lambda row: row[0])
    assert list(query) == [("b", 1), ("d", 1), ("a", 2), ("c", 2)]


def test_then_by_descending_uses_secondary_descending_order() -> None:
    rows = [("a", 2), ("b", 1), ("c", 2), ("d", 1)]
    query = flp.it(rows).order_by(lambda row: row[1]).then_by_descending(lambda row: row[0])
    assert list(query) == [("d", 1), ("b", 1), ("c", 2), ("a", 2)]


def test_then_by_chain_preserves_primary_order() -> None:
    rows = [
        ("b", "z", 2),
        ("a", "y", 2),
        ("b", "a", 1),
        ("a", "b", 1),
    ]
    query = (
        flp.it(rows)
        .order_by(lambda row: row[2])
        .then_by(lambda row: row[0])
        .then_by_descending(lambda row: row[1])
    )
    assert list(query) == [
        ("a", "b", 1),
        ("b", "a", 1),
        ("a", "y", 2),
        ("b", "z", 2),
    ]


def test_order_by_empty_is_empty() -> None:
    query = flp.it([]).order_by(lambda x: x)
    assert list(query) == []
    assert list(query) == []


def test_order_by_key_exception_propagates() -> None:
    def fail(_):
        raise RuntimeError("bad key")

    with pytest.raises(RuntimeError, match="bad key"):
        list(flp.it([1, 2, 3]).order_by(fail))


def test_then_by_key_exception_propagates() -> None:
    def fail(_):
        raise RuntimeError("bad secondary key")

    with pytest.raises(RuntimeError, match="bad secondary key"):
        list(flp.it([1, 2, 3]).order_by(lambda x: x).then_by(fail))


def test_ordering_with_non_comparable_keys_raises() -> None:
    query = flp.it([1, 2]).order_by(lambda x: object())
    with pytest.raises(TypeError):
        list(query)


def test_concurrent_first_iteration_shares_same_cache() -> None:
    calls = 0
    calls_lock = threading.Lock()
    start = threading.Barrier(2)

    def key(x):
        nonlocal calls
        with calls_lock:
            calls += 1
        time.sleep(0.001)
        return x

    query = flp.it([5, 1, 4, 2, 3]).order_by(key)
    results = []

    def worker():
        start.wait()
        results.append(list(query))

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert results == [[1, 2, 3, 4, 5], [1, 2, 3, 4, 5]]
    assert calls == 5

