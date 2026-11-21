"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

The shared producer/consumer suite, ported from
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Collections.Concurrent/tests/ProducerConsumerCollectionTests.cs

Abstract: ``ConcurrentQueue``, ``ConcurrentStack`` and ``ConcurrentBag`` each run it (plus the
shared IEnumerable suite) through a ``Test<UpstreamClass>`` subclass. ``TryTake(out int item)``
leaves ``item`` at ``default`` on failure; here the item is ``None``. ``ThreadFactory.StartNew``
(LongRunning) is ``Task.run(..., creation_options=LONG_RUNNING)``; ``Parallel.For`` runs its range
in chunks on pool tasks; ``Barrier`` is ``threading.Barrier``.

Not portable, skipped: ``ICollection.SyncRoot`` / ``IsSynchronized``, copying into non-zero-lower-bound
or multi-dimensional arrays, and the debugger attribute tests. ``BlockingCollection`` is not provided:
its wrapping test is skipped.
"""
from __future__ import annotations

import os
import random
import threading
import time
from collections.abc import Callable, Iterable
from typing import Any

import pytest

from flpit.concurrent import ProducerConsumerCollection
from flpit.core.linq import ArgumentError, ArgumentNullError, ArgumentOutOfRangeError
from flpit.task import CancellationTokenSource, Task, TaskContinuationOptions, TaskCreationOptions

from nettests.common.collection_helpers import EnumerableOrder, ModifyOperation, next_int, not_portable, unsupported
from nettests.common.ienumerable_generic_tests import IEnumerableGenericTests, ModifyEnumerable

CONCURRENCY_TEST_SECONDS = 1.0
NO_COLLECTION: Any = object()
PROCESSOR_COUNT = os.cpu_count() or 1


def thread_factory_start_new[R](action: Callable[[], R]) -> Task[R]:
    """Upstream ``ThreadFactory.StartNew``: a LongRunning task (a thread of its own)."""
    return Task.run(action, creation_options=TaskCreationOptions.LONG_RUNNING)


def parallel_for(start: int, stop: int, body: Callable[[int], Any]) -> None:
    """.NET ``Parallel.For(start, stop, body)``."""
    chunks = max(1, min(PROCESSOR_COUNT, stop - start))
    size = -(-(stop - start) // chunks)

    def run(low: int) -> None:
        for i in range(low, min(low + size, stop)):
            body(i)

    Task.wait_all([Task.run(lambda low=low: run(low)) for low in range(start, stop, size)])


def wait_all_or_any_failed(*tasks: Task[Any]) -> None:
    if not tasks:
        return

    lock = threading.Lock()
    remaining = [len(tasks)]
    mres = threading.Event()

    def on_done(t: Task[Any]) -> None:
        with lock:
            remaining[0] -= 1
            last = remaining[0] == 0
        if last or t.status == Task.FAILED:
            mres.set()

    for task in tasks:
        task.continue_with(on_done, options=TaskContinuationOptions.EXECUTE_SYNCHRONOUSLY)
    mres.wait()

    for t in tasks:
        if t.status == Task.FAILED:
            t.result()  # propagate for the first one that failed


def assert_sets_equal[T](expected: set[T], actual: set[T]) -> None:
    assert len(expected) == len(actual)
    assert expected <= actual
    assert actual <= expected


class LargeStruct:
    """Used to help validate that values aren't torn while being read."""

    __slots__ = ("_a", "_b", "_c", "_d", "_e", "_f", "_g", "_h")

    def __init__(self, value: int) -> None:
        self._a = self._b = self._c = self._d = self._e = self._f = self._g = self._h = value

    @property
    def value(self) -> int:
        values = (self._a, self._b, self._c, self._d, self._e, self._f, self._g, self._h)
        if len(set(values)) != 1:
            raise AssertionError(f"Inconsistent LargeStruct: {values}")
        return self._a


class ProducerConsumerCollectionTests(IEnumerableGenericTests[int]):
    order = EnumerableOrder.UNSPECIFIED

    def get_modify_enumerables(self, operations: ModifyOperation) -> list[ModifyEnumerable]:
        return []

    def create_t(self, seed: int) -> int:
        return next_int(seed)

    def generic_ienumerable_factory(self, count: int) -> Any:
        return self.create_producer_consumer_collection(range(count))

    def create_producer_consumer_collection(self, collection: Any = NO_COLLECTION) -> ProducerConsumerCollection[Any]:
        """``CreateProducerConsumerCollection()`` without an argument, or from ``collection``."""
        raise NotImplementedError

    def is_empty(self, pcc: Any) -> bool:
        raise NotImplementedError

    def try_peek(self, pcc: Any) -> tuple[bool, Any]:
        raise NotImplementedError

    def create_oracle(self, collection: Iterable[int] = ()) -> Any:
        raise NotImplementedError

    def _create(self, collection: Iterable[Any] = ()) -> Any:
        return self.create_producer_consumer_collection(collection) if collection else self.create_producer_consumer_collection()

    def test_Ctor_InvalidArgs_Throws(self) -> None:
        with pytest.raises(ArgumentNullError, match="'collection'"):
            self.create_producer_consumer_collection(None)

    def test_Ctor_NoArg_ItemsAndCountMatch(self) -> None:
        c = self._create()
        assert 0 == c.count
        assert self.is_empty(c)
        assert [] == list(c)

    @pytest.mark.parametrize("count", [0, 1, 1000])
    def test_Ctor_Collection_ItemsAndCountMatch(self, count: int) -> None:
        c = self._create(range(1, count + 1))
        oracle = self.create_oracle(range(1, count + 1))

        assert (oracle.count == 0) == self.is_empty(c)
        assert oracle.count == c.count
        assert list(oracle) == list(c)

    @pytest.mark.parametrize("num_items", [0, 1, 3, 1000])
    def test_Ctor_InitializeFromCollection_ContainsExpectedItems(self, num_items: int) -> None:
        expected = set(range(num_items))
        pcc = self._create(expected)
        assert len(expected) == pcc.count

        actual: set[int] = set()
        for i in range(len(expected)):
            assert len(expected) - i == pcc.count
            ok, item = pcc.try_take()
            assert ok
            actual.add(item)

        ok, item = pcc.try_take()
        assert not ok
        assert item is None
        assert_sets_equal(expected, actual)

    def test_Add_TakeFromAnotherThread_ExpectedItemsTaken(self) -> None:
        c = self._create()
        assert self.is_empty(c)
        assert 0 == c.count

        num_items = 100000

        def produce() -> None:
            def add(i: int) -> None:
                assert c.try_add(i)

            parallel_for(1, num_items + 1, add)

        producer = Task.run(produce)

        hs: set[int] = set()
        while len(hs) < num_items:
            ok, item = c.try_take()
            if ok:
                hs.add(item)

        producer.result()

        assert self.is_empty(c)
        assert 0 == c.count
        assert_sets_equal(set(range(1, num_items + 1)), hs)

    def test_AddSome_ThenInterleaveAddsAndTakes_MatchesOracle(self) -> None:
        c = self.create_oracle()
        oracle = self._create()

        def take() -> None:
            ok1, item1 = c.try_take()
            assert ok1
            ok2, item2 = oracle.try_take()
            assert ok2
            assert item1 == item2
            assert c.count == oracle.count
            assert list(c) == list(oracle)

        for i in range(100):
            assert oracle.try_add(i)
            assert c.try_add(i)
            assert c.count == oracle.count
            assert list(c) == list(oracle)

            # Start taking some after we've added some
            if i > 50:
                take()

        # Take the rest
        while c.count > 0:
            take()

    def test_AddTake_RandomChangesMatchOracle(self) -> None:
        iters = 1000
        r = random.Random(42)

        c = self._create()
        oracle = self.create_oracle()

        for i in range(iters):
            if r.random() < .5:
                assert oracle.try_add(i) == c.try_add(i)
            else:
                assert oracle.try_take() == c.try_take()

        assert oracle.count == c.count

    @pytest.mark.parametrize(
        ("num_starting_items", "threads_count", "items_per_thread", "take"),
        [(100, 1, 100, True), (100, 4, 10, False), (1000, 11, 100, True), (100000, 2, 50000, True)],
    )
    def test_Initialize_ThenTakeOrPeekInParallel_ItemsObtainedAsExpected(
            self, num_starting_items: int, threads_count: int, items_per_thread: int, take: bool,
    ) -> None:
        c = self._create(range(1, num_starting_items + 1))
        successes = [0]
        lock = threading.Lock()

        b = threading.Barrier(threads_count)

        def work() -> None:
            b.wait()
            for _ in range(items_per_thread):
                ok, data = c.try_take() if take else self.try_peek(c)
                if ok:
                    with lock:
                        successes[0] += 1
                    assert 0 != data  # shouldn't be default(T)

        wait_all_or_any_failed(*(thread_factory_start_new(work) for _ in range(threads_count)))

        assert (num_starting_items if take else threads_count * items_per_thread) == successes[0]

    @pytest.mark.parametrize("count", [0, 1, 1000])
    def test_ToArray_AddAllItemsThenEnumerate_ItemsAndCountMatch(self, count: int) -> None:
        c = self._create()
        oracle = self.create_oracle()

        for i in range(count):
            assert oracle.try_add(i + count) == c.try_add(i + count)

        assert oracle.to_array() == c.to_array()

        if count > 0:
            assert oracle.try_take() == c.try_take()
            assert oracle.to_array() == c.to_array()

    @pytest.mark.parametrize(("initial_count", "iters"), [(1, 10), (2, 10), (10, 10), (100, 10)])
    def test_ToArray_AddAndTakeItemsIntermixedWithEnumeration_ItemsAndCountMatch(self, initial_count: int, iters: int) -> None:
        initial_items = range(1, initial_count + 1)
        c = self._create(initial_items)
        oracle = self.create_oracle(initial_items)

        for i in range(iters):
            assert list(oracle) == list(c)
            assert oracle.try_add(initial_count + i) == c.try_add(initial_count + i)
            assert list(oracle) == list(c)

            assert oracle.try_take() == c.try_take()
            assert list(oracle) == list(c)

    def test_AddFromMultipleThreads_ItemsRemainAfterThreadsGoAway(self) -> None:
        import gc

        c = self._create()

        for i in range(0, 1000, 100):
            def add(i: int = i) -> None:
                for j in range(i, i + 100):
                    assert c.try_add(j)

            thread_factory_start_new(add).result()

            gc.collect()

        assert_sets_equal(set(range(1000)), set(c))

    def test_AddManyItems_ThenTakeOnSameThread_ItemsOutputInExpectedOrder(self) -> None:
        c = self._create(range(100000))
        oracle = self.create_oracle(range(100000))
        for _ in range(99999, -1, -1):
            assert oracle.try_take() == c.try_take()

    def test_TryPeek_SucceedsOnEmptyCollectionThatWasOnceNonEmpty(self) -> None:
        c = self._create()

        for _ in range(2):
            ok, item = self.try_peek(c)
            assert not ok
            assert item is None

        assert c.try_add(42)

        for _ in range(2):
            ok, item = self.try_peek(c)
            assert ok
            assert 42 == item

        ok, item = c.try_take()
        assert ok
        assert 42 == item

        ok, item = self.try_peek(c)
        assert not ok
        assert item is None
        ok, item = c.try_take()
        assert not ok
        assert item is None

    def test_AddTakeWithAtLeastOneElementInCollection_IsEmpty_AlwaysFalse(self) -> None:
        items = 1000

        c = self._create()
        assert c.try_add(0)  # make sure it's never empty
        cts = CancellationTokenSource()

        # Consumer repeatedly calls IsEmpty until it's told to stop
        def consume() -> None:
            while not cts.is_cancellation_requested:
                assert not self.is_empty(c)

        # Producer adds/takes a bunch of items, then tells the consumer to stop
        def produce() -> None:
            for i in range(1, items + 1):
                assert c.try_add(i)
                ok, _ = c.try_take()
                assert ok
            cts.cancel()

        consumer = Task.run(consume)
        producer = Task.run(produce)

        Task.wait_all(producer, consumer)

    def test_CopyTo_Empty_NothingCopied(self) -> None:
        c = self._create()
        c.copy_to([], 0)
        c.copy_to([0] * 10, 10)

    @pytest.mark.parametrize("size", [0, 1, 100])
    def test_CopyTo_SzArray_ZeroIndex_ExpectedElementsCopied(self, size: int) -> None:
        initial_items = range(1, size + 1)

        c = self._create(initial_items)
        actual = [0] * size
        c.copy_to(actual, 0)

        oracle = self.create_oracle(initial_items)
        expected = [0] * size
        oracle.copy_to(expected, 0)

        assert expected == actual

    @pytest.mark.parametrize("size", [0, 1, 100])
    def test_CopyTo_SzArray_NonZeroIndex_ExpectedElementsCopied(self, size: int) -> None:
        initial_items = range(1, size + 1)

        c = self._create(initial_items)
        actual = [0] * (size + 2)
        c.copy_to(actual, 1)

        oracle = self.create_oracle(initial_items)
        expected = [0] * (size + 2)
        oracle.copy_to(expected, 1)

        assert expected == actual

    @pytest.mark.parametrize("size", [0, 1, 100])
    def test_CopyTo_ArrayZeroLowerBound_ZeroIndex_ExpectedElementsCopied(self, size: int) -> None:
        # Array.CreateInstance with a zero lower bound is an ordinary list in Python.
        initial_items = range(1, size + 1)

        c = self._create(initial_items)
        actual = [0] * size
        c.copy_to(actual, 0)

        oracle = self.create_oracle(initial_items)
        expected = [0] * size
        oracle.copy_to(expected, 0)

        assert expected == actual

    def test_CopyTo_ArrayNonZeroLowerBound_ExpectedElementsCopied(self) -> None:
        not_portable("arrays with a non-zero lower bound")

    def test_CopyTo_InvalidArgs_Throws(self) -> None:
        c = self._create(range(10))
        dest = [0] * 10

        with pytest.raises(ArgumentNullError, match="'array'"):
            c.copy_to(None, 0)
        with pytest.raises(ArgumentOutOfRangeError):
            c.copy_to(dest, -1)
        with pytest.raises(ArgumentError):
            c.copy_to(dest, len(dest))
        with pytest.raises(ArgumentError):
            c.copy_to(dest, len(dest) - 2)
        # c.CopyTo(new int[7, 7], 0): multi-dimensional arrays are not portable.

    def test_ICollectionCopyTo_InvalidArgs_Throws(self) -> None:
        # ICollection.CopyTo(Array, int) is the same copy_to in Python.
        c = self._create(range(10))
        dest = [0] * 10

        with pytest.raises(ArgumentNullError, match="'array'"):
            c.copy_to(None, 0)
        with pytest.raises(ArgumentOutOfRangeError):
            c.copy_to(dest, -1)
        with pytest.raises(ArgumentError):
            c.copy_to(dest, len(dest))
        with pytest.raises(ArgumentError):
            c.copy_to(dest, len(dest) - 2)

    def test_BlockingCollection_WrappingCollection_ExpectedElementsTransferred(self) -> None:
        unsupported("BlockingCollection")

    def test_GetEnumerator_NonGeneric(self) -> None:
        c = self._create()
        e = c

        assert not move_next(iter(e))

        assert c.try_add(42)
        assert c.try_add(84)

        hs = set(e)
        assert 2 == len(hs)
        assert 42 in hs
        assert 84 in hs

    def test_GetEnumerator_EnumerationsAreSnapshots(self) -> None:
        c = self._create()
        assert not list(c)

        e1 = iter(c)
        assert c.try_add(1)
        e2 = iter(c)
        assert c.try_add(2)
        e3 = iter(c)
        ok, _ = c.try_take()
        assert ok
        e4 = iter(c)

        assert not move_next(e1)

        assert move_next(e2)
        assert not move_next(e2)

        assert move_next(e3)
        assert move_next(e3)
        assert not move_next(e3)

        assert move_next(e4)
        assert not move_next(e4)

    @pytest.mark.parametrize(
        ("num_items", "consume_from_same_thread"),
        [(0, True), (1, True), (1, False), (10, True), (100, True), (100, False)],
    )
    def test_GetEnumerator_Generic_ExpectedElementsYielded(self, num_items: int, consume_from_same_thread: bool) -> None:
        c = self._create()
        assert not move_next(iter(c))

        # Add, and validate enumeration after each item added
        for i in range(1, num_items + 1):
            assert c.try_add(i)
            assert i == c.count
            assert i == len(set(c))

        # Take, and validate enumerate after each item removed.
        def consume() -> None:
            for i in range(1, num_items + 1):
                ok, _ = c.try_take()
                assert ok
                assert num_items - i == c.count
                assert num_items - i == len(set(c))

        if consume_from_same_thread:
            consume()
        else:
            thread_factory_start_new(consume).result()

    def test_TryAdd_TryTake_ToArray(self) -> None:
        c = self._create()

        assert c.try_add(42)
        assert [42] == c.to_array()

        assert c.try_add(84)
        assert [42, 84] == sorted(c.to_array())

        ok, item = c.try_take()
        assert ok
        remaining_item = 84 if item == 42 else 42
        assert [remaining_item] == c.to_array()
        ok, item = c.try_take()
        assert ok
        assert remaining_item == item
        assert not c.to_array()

    def test_ICollection_IsSynchronized_SyncRoot(self) -> None:
        not_portable("ICollection.IsSynchronized / SyncRoot")

    def test_ToArray_ParallelInvocations_Succeed(self) -> None:
        c = self._create()
        assert not c.to_array()

        num_items = 10000

        def add(i: int) -> None:
            assert c.try_add(i)

        parallel_for(0, num_items, add)
        assert num_items == c.count

        def check(_: int) -> None:
            hs = set(c.to_array())
            assert num_items == len(hs)

        parallel_for(0, 10, check)

    def test_ToArray_AddTakeSameThread_ExpectedResultsAfterAddsAndTakes(self) -> None:
        items = 20

        c = self._create()
        oracle = self.create_oracle()

        for i in range(items):
            assert c.try_add(i)
            assert oracle.try_add(i)
            assert oracle.to_array() == c.to_array()

        for _ in range(items - 1, -1, -1):
            assert oracle.try_take() == c.try_take()
            assert oracle.to_array() == c.to_array()

    def test_GetEnumerator_ParallelInvocations_Succeed(self) -> None:
        c = self._create()
        assert not c.to_array()

        num_items = 10000

        def add(i: int) -> None:
            assert c.try_add(i)

        parallel_for(0, num_items, add)
        assert num_items == c.count

        def check(_: int) -> None:
            hs = set(c)
            assert num_items == len(hs)

        parallel_for(0, 10, check)

    @pytest.mark.parametrize(("threads_per_proc", "seconds"), [(1, CONCURRENCY_TEST_SECONDS / 2), (4, CONCURRENCY_TEST_SECONDS / 2)])
    def test_ManyConcurrentAddsTakes_EnsureTrackedCountsMatchResultingCollection(self, threads_per_proc: int, seconds: float) -> None:
        c = self._create()

        end = [0.0]

        def set_end() -> None:
            end[0] = time.monotonic() + seconds

        b = threading.Barrier(PROCESSOR_COUNT * threads_per_proc, action=set_end)

        def work() -> int:
            b.wait()

            count = 0
            rand = random.Random()
            while time.monotonic() < end[0]:
                if rand.random() < .5:
                    assert c.try_add(rand.randrange(2**31 - 1))
                    count += 1
                else:
                    ok, _ = c.try_take()
                    if ok:
                        count -= 1
            return count

        tasks = [thread_factory_start_new(work) for _ in range(b.parties)]
        Task.wait_all(tasks)
        assert sum(t.result() for t in tasks) == c.count

    @pytest.mark.stress  # [OuterLoop]
    def test_ManyConcurrentAddsTakes_CollectionRemainsConsistent(self) -> None:
        c = self._create()
        operations = 30000

        def add_and_remove() -> None:
            for i in range(1, operations):
                add_count = random.Random(12354).randrange(1, 100)
                for _ in range(add_count):
                    assert c.try_add(i)
                for _ in range(add_count):
                    ok, _ = c.try_take()
                    assert ok

        number_of_threads = 3
        tasks = [thread_factory_start_new(add_and_remove) for _ in range(number_of_threads)]
        wait_all_or_any_failed(*tasks)
        assert not list(c)

    @pytest.mark.parametrize("seconds", [CONCURRENCY_TEST_SECONDS])
    def test_ManyConcurrentAddsTakesPeeks_ForceContentionWithOtherThreadsTaking(self, seconds: float) -> None:
        c = self._create()
        max_count = 4

        end = time.monotonic() + seconds

        def adds_takes_work() -> int:
            total = 0
            while time.monotonic() < end:
                for i in range(1, max_count + 1):
                    assert c.try_add(i)
                    total += 1

                ok, item = self.try_peek(c)
                if ok:
                    assert 1 <= item <= max_count

                for _ in range(1, max_count + 1):
                    ok, item = c.try_take()
                    if ok:
                        total -= 1
                        assert 1 <= item <= max_count
            return total

        def takes_work() -> int:
            total = 0
            while time.monotonic() < end:
                ok, item = c.try_take()
                if ok:
                    total += 1
                    assert 1 <= item <= max_count
            return total

        adds_takes = thread_factory_start_new(adds_takes_work)
        takes_from_other_thread = thread_factory_start_new(takes_work)

        wait_all_or_any_failed(adds_takes, takes_from_other_thread)
        remaining = adds_takes.result() - takes_from_other_thread.result()
        assert 0 <= remaining
        assert remaining == c.count

    @pytest.mark.parametrize("seconds", [CONCURRENCY_TEST_SECONDS])
    def test_ManyConcurrentAddsTakesPeeks_ForceContentionWithOtherThreadsPeeking(self, seconds: float) -> None:
        c = self._create()
        max_count = 4

        end = time.monotonic() + seconds

        def adds_takes_work() -> int:
            total = 0
            while time.monotonic() < end:
                for i in range(1, max_count + 1):
                    assert c.try_add(LargeStruct(i))
                    total += 1

                ok, item = self.try_peek(c)
                assert ok
                assert 1 <= item.value <= max_count

                for _ in range(1, max_count + 1):
                    ok, item = c.try_take()
                    if ok:
                        total -= 1
                        assert 1 <= item.value <= max_count
            return total

        def peeks_work() -> None:
            while time.monotonic() < end:
                ok, item = self.try_peek(c)
                if ok:
                    assert 1 <= item.value <= max_count

        adds_takes = thread_factory_start_new(adds_takes_work)
        peeks_from_other_thread = thread_factory_start_new(peeks_work)

        wait_all_or_any_failed(adds_takes, peeks_from_other_thread)
        assert 0 == adds_takes.result()
        assert 0 == c.count

    @pytest.mark.parametrize("seconds", [CONCURRENCY_TEST_SECONDS])
    def test_ManyConcurrentAddsTakes_ForceContentionWithToArray(self, seconds: float) -> None:
        c = self._create()
        max_count = 4

        end = time.monotonic() + seconds

        def adds_takes_work() -> None:
            while time.monotonic() < end:
                for i in range(1, max_count + 1):
                    assert c.try_add(i)
                for _ in range(1, max_count + 1):
                    ok, item = c.try_take()
                    assert ok
                    assert 1 <= item <= max_count

        adds_takes = thread_factory_start_new(adds_takes_work)

        while time.monotonic() < end:
            arr = c.to_array()
            assert 0 <= len(arr) <= max_count
            assert 0 not in arr  # make sure we didn't get default(T)

        adds_takes.result()
        assert 0 == c.count

    @pytest.mark.parametrize(("initial_count", "seconds"), [(0, CONCURRENCY_TEST_SECONDS / 2), (1, CONCURRENCY_TEST_SECONDS / 2)])
    def test_ManyConcurrentAddsTakes_ForceContentionWithGetEnumerator(self, initial_count: int, seconds: float) -> None:
        c = self._create(range(1, initial_count + 1))
        max_count = 4

        end = time.monotonic() + seconds

        def adds_takes_work() -> None:
            while time.monotonic() < end:
                for i in range(1, max_count + 1):
                    assert c.try_add(i)
                for _ in range(1, max_count + 1):
                    ok, item = c.try_take()
                    assert ok
                    assert 1 <= item <= max_count

        adds_takes = thread_factory_start_new(adds_takes_work)

        while time.monotonic() < end:
            arr = [i for i in c]
            assert initial_count <= len(arr) <= max_count + initial_count
            assert 0 not in arr  # make sure we didn't get default(T)

        adds_takes.result()
        assert initial_count == c.count

    def test_DebuggerAttributes_Success(self) -> None:
        not_portable("debugger display attributes")

    def test_DebuggerTypeProxy_Ctor_NullArgument_Throws(self) -> None:
        not_portable("debugger display attributes")


def move_next(iterator: Any) -> bool:
    """``e.MoveNext()`` on a plain Python iterator."""
    return next(iterator, _END) is not _END


_END = object()
