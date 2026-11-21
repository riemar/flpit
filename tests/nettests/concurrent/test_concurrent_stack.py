"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

ConcurrentStack tests, ported from
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Collections.Concurrent/tests/ConcurrentStackTests.cs

``TestConcurrentStackTests`` also runs the shared ProducerConsumerCollection and IEnumerable suites.
"""
from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any, override

import pytest

from flpit.concurrent import ConcurrentStack
from flpit.core.linq import ArgumentError, ArgumentNullError, ArgumentOutOfRangeError
from flpit.task import Task

from nettests.concurrent.producer_consumer_collection_tests import NO_COLLECTION, ProducerConsumerCollectionTests


class StackOracle:
    def __init__(self, collection: Iterable[int]) -> None:
        self._stack = list(collection)  # top last

    @property
    def count(self) -> int:
        return len(self._stack)

    def copy_to(self, array: list[int], index: int) -> None:
        items = self.to_array()
        array[index:index + len(items)] = items

    def __iter__(self) -> Iterator[int]:
        return iter(self.to_array())

    def to_array(self) -> list[int]:
        return self._stack[::-1]

    def try_add(self, item: int) -> bool:
        self._stack.append(item)
        return True

    def try_take(self) -> tuple[bool, int | None]:
        if self._stack:
            return True, self._stack.pop()
        return False, None


class TestConcurrentStackTests(ProducerConsumerCollectionTests):
    @override
    def create_producer_consumer_collection(self, collection: Any = NO_COLLECTION) -> ConcurrentStack[Any]:
        return ConcurrentStack() if collection is NO_COLLECTION else ConcurrentStack(collection)

    @override
    def is_empty(self, pcc: Any) -> bool:
        return pcc.is_empty

    @override
    def try_peek(self, pcc: Any) -> tuple[bool, Any]:
        return pcc.try_peek()

    @override
    def create_oracle(self, collection: Iterable[int] = ()) -> StackOracle:
        return StackOracle(collection)

    def test_IsEmpty_TrueWhenEmpty_FalseWhenNot(self) -> None:
        s: ConcurrentStack[int] = ConcurrentStack()

        assert not s.try_pop()[0]
        assert not s.try_peek()[0]
        assert 0 == s.try_pop_range([0])

        count = 15
        for i in range(count):
            s.push(i)
        assert 0 == s.try_pop_range([0], 0, 0)
        assert count == s.count
        assert not s.is_empty

    @pytest.mark.parametrize("count", [0, 16, 1024])
    def test_Clear_AllElementsRemoved(self, count: int) -> None:
        s = ConcurrentStack(range(count))
        assert count == s.count
        s.clear()
        assert s.is_empty
        assert 0 == s.count

    def test_PushRange_NoItems_NothingAdded(self) -> None:
        s: ConcurrentStack[int] = ConcurrentStack()
        assert s.is_empty

        s.push_range([0], 0, 0)
        assert s.is_empty

    def test_PushRange_NoItems_NothingAdded_EmptyArrayWithRangeSpecified(self) -> None:
        s: ConcurrentStack[int] = ConcurrentStack()
        assert s.is_empty

        s.push_range([], 0, 0)
        assert s.is_empty

    def test_PushRange_NoItems_NothingAdded_NonEmptyArrayWithZeroCountSpecified(self) -> None:
        s: ConcurrentStack[int] = ConcurrentStack()
        assert s.is_empty

        arr = [0, 0]
        s.push_range(arr, len(arr), 0)
        assert s.is_empty

    def test_PushRange_NoItems_NothingAdded_EmptyArrayNoRangeSpecified(self) -> None:
        s: ConcurrentStack[int] = ConcurrentStack()
        assert s.is_empty

        s.push_range([])
        assert s.is_empty

    @pytest.mark.parametrize(("num_threads", "num_items_per_thread"), [(8, 10), (16, 100), (128, 100)])
    def test_PushRange_Concurrent_ConsecutiveItemsInEachRange(self, num_threads: int, num_items_per_thread: int) -> None:
        stack: ConcurrentStack[int] = ConcurrentStack()

        def push(index: int) -> None:
            array = [index + j for j in range(num_items_per_thread)]
            stack.push_range(array)

        Task.wait_all([Task.run(lambda i=i: push(i * num_items_per_thread)) for i in range(num_threads)])

        for _ in range(num_threads):
            last_item = -1
            for _ in range(num_items_per_thread):
                ok, current_item = stack.try_pop()
                assert ok
                assert last_item <= -1 or last_item - current_item == 1
                last_item = current_item

    @pytest.mark.parametrize(("num_threads", "num_elements_per_thread"), [(8, 10), (16, 100), (128, 100)])
    def test_TryPopRange_Concurrent_PoppedItemsAreConsecutive(self, num_threads: int, num_elements_per_thread: int) -> None:
        num_total_elements = num_threads * num_elements_per_thread
        all_values = list(range(1, num_total_elements + 1))
        stack = ConcurrentStack(all_values)

        array = [0] * num_total_elements

        def pop(index: int) -> None:
            res = stack.try_pop_range(array, index, num_elements_per_thread)
            assert num_elements_per_thread == res

        Task.wait_all([Task.run(lambda i=i: pop(i * num_elements_per_thread)) for i in range(num_threads)])

        for i in range(num_threads):
            for j in range(1, num_elements_per_thread):
                current_index = i * num_elements_per_thread + j
                assert array[current_index - 1] == array[current_index] + 1

    def test_PushRange_InvalidArguments_Throws(self) -> None:
        stack: ConcurrentStack[int] = ConcurrentStack()
        with pytest.raises(ArgumentNullError):
            stack.push_range(None)  # type: ignore[arg-type]
        with pytest.raises(ArgumentNullError):
            stack.push_range(None, 0, 0)  # type: ignore[arg-type]
        with pytest.raises(ArgumentOutOfRangeError):
            stack.push_range([0], 0, -1)
        with pytest.raises(ArgumentOutOfRangeError):
            stack.push_range([0], -1, 1)
        with pytest.raises(ArgumentOutOfRangeError):
            stack.push_range([0], 2, 1)
        with pytest.raises(ArgumentError):
            stack.push_range([], 0, 1)
        with pytest.raises(ArgumentError):
            stack.push_range([0], 0, 10)

    def test_TryPopRange_InvalidArguments_Throws(self) -> None:
        stack: ConcurrentStack[int] = ConcurrentStack()
        with pytest.raises(ArgumentNullError):
            stack.try_pop_range(None)  # type: ignore[arg-type]
        with pytest.raises(ArgumentNullError):
            stack.try_pop_range(None, 0, 0)  # type: ignore[arg-type]
        with pytest.raises(ArgumentOutOfRangeError):
            stack.try_pop_range([0], 0, -1)
        with pytest.raises(ArgumentOutOfRangeError):
            stack.try_pop_range([0], -1, 1)
        with pytest.raises(ArgumentOutOfRangeError):
            stack.try_pop_range([0], 2, 1)
        with pytest.raises(ArgumentError):
            stack.try_pop_range([0], 0, 10)

    def test_Concurrent_Push_TryPop_WithSuspensions(self) -> None:
        items = 10

        q: ConcurrentStack[int] = ConcurrentStack()

        def consume() -> None:
            while True:
                ok, item = q.try_pop()
                if ok and item == items:
                    break

        def produce() -> None:
            import gc

            for i in range(1, items + 1):
                q.push(i)
                gc.collect(0)  # GC.GetTotalAllocatedBytes(precise: true): a pause

        consumer = Task.run(consume)
        producer = Task.run(produce)

        Task.wait_all(producer, consumer)
