"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

ConcurrentQueue tests, ported from
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Collections.Concurrent/tests/ConcurrentQueueTests.cs

``TestConcurrentQueueTests`` also runs the shared ProducerConsumerCollection and IEnumerable suites.
``Volatile.Read`` / ``Write`` are plain attribute reads / writes; a finalizer is ``__del__``.
"""
from __future__ import annotations

import gc
import random
import threading
import time
from collections import deque
from collections.abc import Iterable, Iterator
from typing import Any, override

import pytest

from flpit.concurrent import ConcurrentQueue
from flpit.task import Task

from nettests.concurrent.producer_consumer_collection_tests import (
    NO_COLLECTION,
    PROCESSOR_COUNT,
    ProducerConsumerCollectionTests,
    move_next,
    parallel_for,
    thread_factory_start_new,
)


class QueueOracle:
    def __init__(self, collection: Iterable[int]) -> None:
        self._queue = deque(collection)

    @property
    def count(self) -> int:
        return len(self._queue)

    def copy_to(self, array: list[int], index: int) -> None:
        array[index:index + len(self._queue)] = self._queue

    def __iter__(self) -> Iterator[int]:
        return iter(self._queue)

    def to_array(self) -> list[int]:
        return list(self._queue)

    def try_add(self, item: int) -> bool:
        self._queue.append(item)
        return True

    def try_take(self) -> tuple[bool, int | None]:
        if self._queue:
            return True, self._queue.popleft()
        return False, None


class TestConcurrentQueueTests(ProducerConsumerCollectionTests):
    @override
    def create_producer_consumer_collection(self, collection: Any = NO_COLLECTION) -> ConcurrentQueue[Any]:
        return ConcurrentQueue() if collection is NO_COLLECTION else ConcurrentQueue(collection)

    @override
    def is_empty(self, pcc: Any) -> bool:
        return pcc.is_empty

    @override
    def try_peek(self, pcc: Any) -> tuple[bool, Any]:
        return pcc.try_peek()

    @override
    def create_oracle(self, collection: Iterable[int] = ()) -> QueueOracle:
        return QueueOracle(collection)

    def test_Concurrent_TryDequeue_DoesNotReportEmptyWhileItemsAreQueued(self) -> None:
        # Even if there are items in the queue, try_dequeue may report empty if another thread
        # is in the middle of adding; a queue with items and no adds in progress never does.
        worker_count = 4
        q: ConcurrentQueue[object] = ConcurrentQueue()
        for _ in range(worker_count):
            q.enqueue(object())

        stop = [False]
        false_empties = [0]
        lock = threading.Lock()

        def snapshot() -> None:
            while not stop[0]:
                q.to_array()

        snapshotter = Task.run(snapshot)

        def work() -> None:
            while not stop[0]:
                ok, item = q.try_dequeue()
                if not ok:
                    with lock:
                        false_empties[0] += 1
                    item = object()
                q.enqueue(item)

        workers = [Task.run(work) for _ in range(worker_count)]

        time.sleep(0.2)
        stop[0] = True
        Task.wait_all(workers)
        snapshotter.wait()
        assert 0 == false_empties[0]

    def test_Concurrent_Enqueue_TryDequeue_AllItemsReceived(self) -> None:
        items = 1000

        q: ConcurrentQueue[int] = ConcurrentQueue()

        # Consumer dequeues items until it gets as many as it expects
        def consume() -> None:
            last_received = 0
            while True:
                ok, item = q.try_dequeue()
                if ok:
                    assert last_received + 1 == item
                    last_received = item
                    if item == items:
                        break
                else:
                    assert item is None

        # Producer queues the expected number of items
        def produce() -> None:
            for i in range(1, items + 1):
                q.enqueue(i)

        consumer = Task.run(consume)
        producer = Task.run(produce)

        Task.wait_all(producer, consumer)

    def test_Concurrent_Enqueue_TryPeek_TryDequeue_AllItemsSeen(self) -> None:
        items = 1000

        q: ConcurrentQueue[int] = ConcurrentQueue()

        # Consumer peeks and then dequeues the expected number of items
        def consume() -> None:
            last_received = 0
            while True:
                ok, item = q.try_peek()
                if ok:
                    assert last_received + 1 == item
                    ok, item = q.try_dequeue()
                    assert ok
                    assert last_received + 1 == item
                    last_received = item
                    if item == items:
                        break

        # Producer queues the expected number of items
        def produce() -> None:
            for i in range(1, items + 1):
                q.enqueue(i)

        consumer = Task.run(consume)
        producer = Task.run(produce)

        Task.wait_all(producer, consumer)

    @pytest.mark.parametrize(("producers", "consumers", "items_per_producer"), [(1, 4, 1024), (4, 1, 1024), (3, 3, 1024)])
    def test_MultipleProducerConsumer_AllItemsTransferred(self, producers: int, consumers: int, items_per_producer: int) -> None:
        cq: ConcurrentQueue[int] = ConcurrentQueue()
        tasks: list[Task[None]] = []

        total_items = producers * items_per_producer
        remaining_items = [total_items]
        total = [0]
        lock = threading.Lock()

        def consume() -> None:
            while remaining_items[0] > 0:
                ok, item = cq.try_dequeue()
                if ok:
                    with lock:
                        total[0] += item
                        remaining_items[0] -= 1

        def produce() -> None:
            for item in range(1, items_per_producer + 1):
                cq.enqueue(item)

        for _ in range(consumers):
            tasks.append(thread_factory_start_new(consume))

        for _ in range(producers):
            tasks.append(thread_factory_start_new(produce))

        Task.wait_all(tasks)

        assert producers * (items_per_producer * (items_per_producer + 1) // 2) == total[0]

    @pytest.mark.parametrize(("count", "via_interface"), [(1, False), (100, False), (512, False), (1, True), (100, True), (512, True)])
    def test_CopyTo_AllItemsCopiedAtCorrectLocation(self, count: int, via_interface: bool) -> None:
        # ICollection.CopyTo and CopyTo are the same copy_to in Python.
        q = ConcurrentQueue(range(count))
        arr = [0] * count
        q.copy_to(arr, 0)
        assert list(q) == arr

        if count > 1:
            to_remove = count // 2
            remaining = count - to_remove
            for i in range(to_remove):
                ok, item = q.try_dequeue()
                assert ok
                assert i == item

            q.copy_to(arr, 1)

            assert 0 == arr[0]
            for i in range(remaining):
                assert arr[1 + i] == i + to_remove

    def test_IEnumerable_GetAllExpectedItems(self) -> None:
        enumerable1 = ConcurrentQueue(range(1, 6))
        enumerable2 = enumerable1

        expected_next = 1
        enumerator1 = iter(enumerable1)
        enumerator2 = iter(enumerable2)
        for current in enumerator1:
            assert next(enumerator2) == current
            assert expected_next == current
            expected_next += 1
        assert not move_next(enumerator2)
        assert 6 == expected_next

    def test_ReferenceTypes_NulledAfterDequeue(self) -> None:
        iterations = 10  # any number <32 will do
        mres = [threading.Event() for _ in range(iterations)]

        def fill_and_drain() -> ConcurrentQueue[Finalizable]:
            q: ConcurrentQueue[Finalizable] = ConcurrentQueue()
            for i in range(iterations):
                q.enqueue(Finalizable(mres[i]))
            for _ in range(iterations):
                ok, _temp = q.try_dequeue()
                assert ok
            return q

        queue = fill_and_drain()

        gc.collect()
        assert all(e.is_set() for e in mres)
        assert queue is not None  # GC.KeepAlive(queue)

    def test_ManySegments_ConcurrentDequeues_RemainsConsistent(self) -> None:
        cq: ConcurrentQueue[int] = ConcurrentQueue()
        iters = 10000

        for i in range(iters):
            cq.enqueue(i)
            iter(cq)  # force new segment

        dequeues = [0]
        lock = threading.Lock()

        def drain(_: int) -> None:
            while not cq.is_empty:
                ok, _item = cq.try_dequeue()
                if ok:
                    with lock:
                        dequeues[0] += 1

        parallel_for(0, PROCESSOR_COUNT, drain)

        assert 0 == cq.count
        assert cq.is_empty
        assert iters == dequeues[0]

    def test_ManySegments_ConcurrentEnqueues_RemainsConsistent(self) -> None:
        cq: ConcurrentQueue[int] = ConcurrentQueue()

        items_per_thread = 1000
        threads = PROCESSOR_COUNT

        def fill(i: int) -> None:
            for item in range(items_per_thread):
                cq.enqueue(item + (i * items_per_thread))
                iter(cq)

        parallel_for(0, threads, fill)

        assert items_per_thread * threads == cq.count
        assert list(range(items_per_thread * threads)) == sorted(cq)

    @pytest.mark.parametrize("count", [0, 1, 1000])
    def test_Clear_CountMatch(self, count: int) -> None:
        q = ConcurrentQueue(range(1, count + 1))
        assert count == q.count

        # Clear initial items
        q.clear()
        assert 0 == q.count
        assert q.is_empty
        assert [] == list(q)

        # Clear again has no effect
        q.clear()
        assert q.is_empty

        # Add more items then clear and verify
        for i in range(count):
            q.enqueue(i)
        assert list(range(count)) == list(q)
        q.clear()
        assert 0 == q.count
        assert q.is_empty
        assert [] == list(q)

        # Add items and clear after each item
        for i in range(count):
            q.enqueue(i)
            assert 1 == q.count
            q.clear()
            assert 0 == q.count

    def test_Clear_DuringEnumeration_DoesntAffectEnumeration(self) -> None:
        expected_count = 100
        q = ConcurrentQueue(range(expected_count))
        before_clear = iter(q)
        q.clear()
        after_clear = iter(q)
        assert expected_count == sum(1 for _ in before_clear)
        assert 0 == sum(1 for _ in after_clear)

    @pytest.mark.parametrize(("threads_count", "items_per_thread"), [(1, 10), (3, 100), (8, 1000)])
    def test_Concurrent_Clear_NoExceptions(self, threads_count: int, items_per_thread: int) -> None:
        q: ConcurrentQueue[int] = ConcurrentQueue()

        def work() -> None:
            rand = random.Random()
            for _ in range(items_per_thread):
                match rand.randrange(7):
                    case 0:
                        _ = q.count
                    case 1:
                        _ = q.is_empty
                    case 2:
                        q.enqueue(rand.randrange(2**31 - 1))
                    case 3:
                        q.to_array()
                    case 4:
                        q.try_dequeue()
                    case 5:
                        q.try_peek()
                    case 6:
                        q.clear()

        Task.wait_all([Task.run(work) for _ in range(threads_count)])


class Finalizable:
    def __init__(self, mres: threading.Event) -> None:
        self._mres = mres

    def __del__(self) -> None:
        self._mres.set()
