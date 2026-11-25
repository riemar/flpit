"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

ConcurrentBag tests, ported from
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Collections.Concurrent/tests/ConcurrentBagTests.cs

``TestConcurrentBagTests`` also runs the shared ProducerConsumerCollection and IEnumerable suites.
The ordering asserts ("implementation detail that's not guaranteed") hold for flpit's bag too:
a thread takes its own newest item first, else steals another thread's oldest.

Not portable, skipped: ``CopyTo_TypeMismatch`` / ``ICollectionCopyTo_TypeMismatch`` (Python lists
are untyped: no ``InvalidCastException``).
"""
from __future__ import annotations

import threading
from collections.abc import Iterable, Iterator
from typing import Any, override

import pytest

from flpit.concurrent import ConcurrentBag
from flpit.task import Task
from flpit.threading import SemaphoreSlim

from nettests.common.collection_helpers import not_portable
from nettests.concurrent.producer_consumer_collection_tests import (
    NO_COLLECTION,
    ProducerConsumerCollectionTests,
    thread_factory_start_new,
    wait_all_or_any_failed,
)


class BagOracle:
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


class TestConcurrentBagTests(ProducerConsumerCollectionTests):
    enumerator_empty_uses_singleton_instance = True

    @override
    def create_producer_consumer_collection(self, collection: Any = NO_COLLECTION) -> ConcurrentBag[Any]:
        return ConcurrentBag() if collection is NO_COLLECTION else ConcurrentBag(collection)

    @override
    def is_empty(self, pcc: Any) -> bool:
        return pcc.is_empty

    @override
    def try_peek(self, pcc: Any) -> tuple[bool, Any]:
        return pcc.try_peek()

    @override
    def create_oracle(self, collection: Iterable[int] = ()) -> BagOracle:
        return BagOracle(collection)

    @pytest.mark.parametrize(("threads_count", "items_per_thread"), [(1, 10), (3, 100), (8, 1000)])
    def test_AddThenPeek_LatestLocalItemReturned(self, threads_count: int, items_per_thread: int) -> None:
        bag: ConcurrentBag[int] = ConcurrentBag()

        b = threading.Barrier(threads_count)

        def work() -> None:
            b.wait()
            for i in range(1, items_per_thread + 1):
                bag.add(i)
                ok, item = bag.try_peek()
                assert ok  # ordering implementation detail that's not guaranteed
                assert i == item

        wait_all_or_any_failed(*(thread_factory_start_new(work) for _ in range(threads_count)))

        assert items_per_thread * threads_count == bag.count

    def test_AddOnOneThread_PeekOnAnother_EnsureWeCanTakeOnTheOriginal(self) -> None:
        bag = ConcurrentBag(range(1, 6))

        def peek() -> None:
            for _ in range(1, 6):
                ok, item = bag.try_peek()
                assert ok
                assert 1 == item

        thread_factory_start_new(peek).result()

        assert 5 == bag.count

        for i in range(5, 0, -1):
            ok, item = bag.try_peek()
            assert ok
            assert i == item  # ordering implementation detail that's not guaranteed

            assert i == bag.count
            ok, item = bag.try_take()
            assert ok
            assert i - 1 == bag.count
            assert i == item  # ordering implementation detail that's not guaranteed

    def test_AddManyItems_ThenTakeOnDifferentThread_ItemsOutputInExpectedOrder(self) -> None:
        bag = ConcurrentBag(range(100000))

        def take() -> None:
            for i in range(100000):
                ok, item = bag.try_take()
                assert ok
                assert i == item  # Testing an implementation detail rather than guaranteed ordering

        thread_factory_start_new(take).result()

    def test_SingleProducerAdding_MultiConsumerTaking_SemaphoreThrottling_AllTakesSucceed(self) -> None:
        bag: ConcurrentBag[int] = ConcurrentBag()
        s = SemaphoreSlim(0)
        item_count = 200_000
        lock = threading.Lock()
        consumed = [0]
        done = threading.Semaphore(0)  # CountdownEvent(3)

        # Upstream re-queues a work item per step; a loop per participant does the same work
        # without a recursion depth of 200,000.
        def producer() -> None:
            for value in range(item_count):
                bag.add(value)
                s.release()
            done.release()

        def consumer() -> None:
            while True:
                if s.wait(0):
                    ok, _ = bag.try_take()
                    assert ok, "There's an item available, but we couldn't take it."
                    with lock:
                        consumed[0] += 1
                elif consumed[0] >= item_count:
                    done.release()
                    return

        tasks = [thread_factory_start_new(producer), thread_factory_start_new(consumer), thread_factory_start_new(consumer)]
        for _ in range(3):
            done.acquire()
        Task.wait_all(tasks)

    @pytest.mark.parametrize("initial_count", [0, 1, 10, 33])
    def test_IterativelyAddOnOneThreadThenTakeOnAnother_OrderMaintained(self, initial_count: int) -> None:
        bag = ConcurrentBag(range(initial_count))

        iterations = 100
        item_consumed = threading.Event()
        item_produced = threading.Event()

        def take() -> None:
            for i in range(iterations):
                item_produced.wait()
                item_produced.clear()
                ok, item = bag.try_take()
                assert ok
                assert i == item  # Testing an implementation detail rather than guaranteed ordering
                item_consumed.set()

        t = Task.run(take)

        for i in range(initial_count, iterations + initial_count):
            bag.add(i)
            item_produced.set()
            item_consumed.wait()
            item_consumed.clear()

        t.result()
        assert initial_count == bag.count

    def test_CopyTo_TypeMismatch(self) -> None:
        not_portable("typed arrays: Python lists accept any item, so there is no InvalidCastException")

    def test_ICollectionCopyTo_TypeMismatch(self) -> None:
        not_portable("typed arrays: Python lists accept any item, so there is no InvalidCastException")

    @pytest.mark.parametrize("initial_count", [0, 1, 10])
    def test_ToArray_AddTakeDifferentThreads_ExpectedResultsAfterAddsAndTakes(self, initial_count: int) -> None:
        bag = ConcurrentBag(range(initial_count))
        items = 20 + initial_count

        for i in range(items):
            bag.add(i + initial_count)

            def take(i: int = i) -> None:
                ok, item = bag.try_take()
                assert ok
                assert item == i

            thread_factory_start_new(take).result()
            assert list(range(i + 1, i + 1 + initial_count))[::-1] == bag.to_array()

    @pytest.mark.parametrize(
        ("add_to_local_thread", "other_threads"),
        [(False, 0), (False, 1), (False, 20), (True, 0), (True, 1), (True, 20)],
    )
    def test_Clear_AddItemsToThisAndOtherThreads_EmptyAfterClear(self, add_to_local_thread: bool, other_threads: int) -> None:
        bag: ConcurrentBag[int] = ConcurrentBag()

        items_per_thread = 100

        for _ in range(2):
            # If desired, add items on the current thread
            if add_to_local_thread:
                for i in range(items_per_thread):
                    bag.add(i)

            # Add items on other threads
            orig_thread_id = threading.get_ident()

            def add() -> None:
                assert orig_thread_id != threading.get_ident()
                for i in range(items_per_thread):
                    bag.add(i)

            Task.wait_all([thread_factory_start_new(add) for _ in range(other_threads)])

            # Make sure we got the right number of items, then clear, and make sure it's empty
            assert (items_per_thread * other_threads) + (items_per_thread if add_to_local_thread else 0) == bag.count
            bag.clear()
            assert 0 == bag.count

    def test_Clear_AfterRemoval_DoesNotExposeOldItems(self) -> None:
        bag = ConcurrentBag([1, 2, 3])
        assert bag.try_take()[0]

        bag.clear()
        assert list(bag) == []
        assert not bag.try_peek()[0]
        assert not bag.try_take()[0]

        bag.add(4)
        bag.add(5)
        assert [4, 5] == sorted(bag)
        remaining = {4, 5}
        while True:
            ok, item = bag.try_take()
            if not ok:
                break
            assert item in remaining
            remaining.remove(item)
        assert not remaining

    def test_Clear_DuringEnumeration_DoesntAffectEnumeration(self) -> None:
        expected_count = 100
        bag = ConcurrentBag(range(expected_count))
        e = iter(bag)
        bag.clear()
        assert expected_count == sum(1 for _ in e)

    @pytest.mark.parametrize(("threads_count", "items_per_thread"), [(1, 10), (3, 100), (8, 1000)])
    def test_Clear_ConcurrentUsage_NoExceptions(self, threads_count: int, items_per_thread: int) -> None:
        import random

        bag: ConcurrentBag[int] = ConcurrentBag()

        def work() -> None:
            rand = random.Random()
            for j in range(items_per_thread):
                match rand.randrange(5):
                    case 0:
                        bag.add(j)
                    case 1:
                        bag.try_peek()
                    case 2:
                        bag.try_take()
                    case 3:
                        bag.clear()
                    case 4:
                        bag.to_array()

        Task.wait_all([thread_factory_start_new(work) for _ in range(threads_count)])
